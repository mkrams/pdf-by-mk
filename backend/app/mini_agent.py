"""
Phase 2: Mini-agent — analyzes a single candidate change with a fresh,
focused context window. Receives pre-extracted page text and produces
a classified ChangeItem.

This runs synchronously in a worker thread.
"""
import json
import time
import anthropic
from datetime import datetime

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .pdf_utils import extract_page_text, search_document

MINI_AGENT_SYSTEM_PROMPT = """\
You are analyzing a single document change between an old and new PDF version.
You will receive the relevant page text from both documents and a description
of what changed.

Your job:
1. Read the provided page text carefully
2. Identify the exact change (what was there before vs what is there now)
3. Classify it precisely
4. Call save_change with the complete analysis

Required fields for save_change:
- section: the section/table/appendix reference (e.g., "2.3", "Table 3")
- title: brief human-readable title (e.g., "Updated test frequency requirement")
- category: NEW, MODIFIED, REMOVED, or STRUCTURAL
- description: 1-2 sentence explanation of what changed and why it matters
- old_text: exact quote from old document (max 300 chars). Use "" if NEW.
- new_text: exact quote from new document (max 300 chars). Use "" if REMOVED.
- impact: "LEVEL — explanation" where LEVEL is CRITICAL/HIGH/MEDIUM/LOW
- search_old: short unique snippet (10-40 chars) to find in old PDF for annotation
- search_new: short unique snippet (10-40 chars) to find in new PDF for annotation
- verification_status: "verified" or "needs_review"
- verification_conclusion: brief verification summary
- verification_keywords: list of key terms related to this change

Be precise with old_text and new_text — these are shown to the user for comparison.
The search_old and search_new snippets must be unique enough to find the right location.

If the page text doesn't contain a real change (false positive), call save_change
with category "FALSE_POSITIVE" and it will be filtered out.
"""

MINI_AGENT_TOOLS = [
    {
        "name": "extract_pdf_page",
        "description": "Extract text from a specific page of a PDF. Use if you need adjacent pages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
                "page_number": {"type": "integer", "description": "1-indexed page number"},
            },
            "required": ["pdf_id", "page_number"],
        },
    },
    {
        "name": "search_document",
        "description": "Search for specific text in a PDF. Use to verify presence/absence of content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
                "query": {"type": "string", "description": "Text to search for"},
            },
            "required": ["pdf_id", "query"],
        },
    },
    {
        "name": "save_change",
        "description": (
            "Save the classified change. Call this exactly once when you have "
            "completed your analysis. This persists the change and streams it "
            "to the user immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "title": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["NEW", "MODIFIED", "REMOVED", "STRUCTURAL", "FALSE_POSITIVE"],
                },
                "description": {"type": "string"},
                "old_text": {"type": "string", "default": ""},
                "new_text": {"type": "string", "default": ""},
                "impact": {"type": "string", "description": "LEVEL — explanation"},
                "manifest_item": {"type": "string", "default": ""},
                "verification_status": {"type": "string", "default": "verified"},
                "verification_conclusion": {"type": "string", "default": ""},
                "verification_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "search_old": {"type": "string", "default": ""},
                "search_new": {"type": "string", "default": ""},
            },
            "required": ["section", "title", "category", "description", "impact"],
        },
    },
]

MAX_MINI_AGENT_TURNS = 4
MINI_AGENT_TIMEOUT = 90  # seconds


def run_mini_agent(
    job_id: str,
    candidate: dict,
    page_cache: dict,
    old_pdf_path: str,
    new_pdf_path: str,
    api_key: str = "",
    change_callback=None,
) -> dict:
    """
    Analyze a single candidate change with a focused mini-agent.

    candidate: {id, section, title, category_hint, old_pages, new_pages, diff_preview, manifest_item}
    page_cache: {("old"|"new", page_num): "text", ...}
    change_callback: callable(change_dict) — called when change is classified

    Returns: {"agent_id": str, "change": dict or None, "tokens_used": int, "error": str or None}
    """
    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        return {"agent_id": candidate["id"], "change": None, "tokens_used": 0,
                "error": "No API key"}

    client = anthropic.Anthropic(api_key=effective_key)
    start = time.time()
    cand_id = candidate["id"]
    tokens_used = 0

    # Build focused user message with pre-extracted page text
    old_text_parts = []
    for page in candidate.get("old_pages", []):
        text = page_cache.get(("old", page), "")
        if text:
            old_text_parts.append(f"--- OLD Page {page} ---\n{text}")

    new_text_parts = []
    for page in candidate.get("new_pages", []):
        text = page_cache.get(("new", page), "")
        if text:
            new_text_parts.append(f"--- NEW Page {page} ---\n{text}")

    old_text_block = "\n\n".join(old_text_parts) if old_text_parts else "(no pages available — use extract_pdf_page to read)"
    new_text_block = "\n\n".join(new_text_parts) if new_text_parts else "(no pages available — use extract_pdf_page to read)"

    user_msg = (
        f"## Candidate Change: {candidate['section']}\n\n"
        f"**Category hint**: {candidate['category_hint']}\n"
        f"**Diff preview**: {candidate.get('diff_preview', 'N/A')}\n"
    )
    if candidate.get("manifest_item"):
        user_msg += f"**Manifest entry**: {candidate['manifest_item']}\n"

    user_msg += (
        f"\n### Old Document Text\n{old_text_block}\n\n"
        f"### New Document Text\n{new_text_block}\n\n"
        f"Analyze this change and call save_change with your classification."
    )

    messages = [{"role": "user", "content": user_msg}]
    saved_change = None

    for turn in range(MAX_MINI_AGENT_TURNS):
        # Timeout check
        if time.time() - start > MINI_AGENT_TIMEOUT:
            print(f"[mini-agent {cand_id}] Timeout at turn {turn+1}")
            break

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=MINI_AGENT_SYSTEM_PROMPT,
                tools=MINI_AGENT_TOOLS,
                messages=messages,
                temperature=0,
            )
        except anthropic.RateLimitError:
            # Wait and retry once
            print(f"[mini-agent {cand_id}] Rate limited, waiting 10s...")
            time.sleep(10)
            try:
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4096,
                    system=MINI_AGENT_SYSTEM_PROMPT,
                    tools=MINI_AGENT_TOOLS,
                    messages=messages,
                    temperature=0,
                )
            except Exception as e:
                print(f"[mini-agent {cand_id}] Retry failed: {e}")
                return {"agent_id": cand_id, "change": None, "tokens_used": tokens_used,
                        "error": str(e)}
        except Exception as e:
            print(f"[mini-agent {cand_id}] API error: {e}")
            return {"agent_id": cand_id, "change": None, "tokens_used": tokens_used,
                    "error": str(e)}

        tokens_used += response.usage.input_tokens + response.usage.output_tokens
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        tool_blocks = [b for b in assistant_content if b.type == "tool_use"]
        if not tool_blocks:
            break  # Agent done without saving — shouldn't happen but handle gracefully

        tool_results = []
        for block in tool_blocks:
            if block.name == "save_change":
                change = block.input
                change["manifest_item"] = change.get("manifest_item") or candidate.get("manifest_item", "")

                # Filter false positives
                if change.get("category") == "FALSE_POSITIVE":
                    print(f"[mini-agent {cand_id}] Marked as false positive, skipping")
                    saved_change = None
                else:
                    saved_change = change
                    if change_callback:
                        change_callback(change)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({"status": "saved"}),
                })

            elif block.name == "extract_pdf_page":
                pdf_path = old_pdf_path if block.input.get("pdf_id") == "old" else new_pdf_path
                result = extract_page_text(pdf_path, block.input.get("page_number", 1))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })

            elif block.name == "search_document":
                pdf_path = old_pdf_path if block.input.get("pdf_id") == "old" else new_pdf_path
                result = search_document(pdf_path, block.input.get("query", ""))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({"error": f"Unknown tool: {block.name}"}),
                })

        messages.append({"role": "user", "content": tool_results})

        # If we got a save_change, we're done
        if saved_change is not None:
            break

    elapsed = round(time.time() - start, 1)
    print(f"[mini-agent {cand_id}] Done in {elapsed}s, tokens={tokens_used}, "
          f"change={'yes' if saved_change else 'no'}")

    return {
        "agent_id": cand_id,
        "change": saved_change,
        "tokens_used": tokens_used,
        "error": None,
    }
