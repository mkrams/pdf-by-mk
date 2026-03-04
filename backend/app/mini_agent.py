"""
Phase 2: Mini-agent — two-pass architecture for analyzing candidate changes.

Pass 1 (Sonnet): Fast, single-turn. Gets candidate + page text, returns a
         structured decision: ACCEPT (save_change), REJECT (false positive),
         or UNCERTAIN (needs more context).

Pass 2 (Opus):   Only for UNCERTAIN candidates. Gets richer context (more pages,
         Sonnet's notes) and makes the final call. Single turn, no tools.

No agentic loop, no tools, no timeouts.
"""
import json
import time
import anthropic
from datetime import datetime

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .pdf_utils import extract_page_text


# ── PASS 1: Sonnet (fast triage) ────────────────────────────────────

PASS1_SYSTEM_PROMPT = """\
You are analyzing a single document change between an old and new PDF version.
The orchestrator has already identified this as a candidate change via programmatic diff.

Your job is to examine the provided page text and make ONE of three decisions:

1. **SAVE**: You can clearly see the change. Provide full classification.
2. **FALSE_POSITIVE**: You are 100% certain the old and new text are completely \
identical with zero differences. This should be extremely rare.
3. **UNCERTAIN**: You cannot confidently determine the change from the provided \
context. Maybe the page text doesn't cover the right area, the section spans \
pages you don't have, or the text extraction is garbled.

IMPORTANT BIAS: The diff found a difference, so there almost certainly IS one. \
When in doubt between SAVE and UNCERTAIN, lean toward SAVE. Only use UNCERTAIN \
if you genuinely cannot see what changed in the provided text.

Respond with a JSON object (no markdown fences):

For SAVE:
{
  "decision": "SAVE",
  "section": "section ref (e.g. 2.3, Table 3)",
  "title": "brief human-readable title",
  "category": "NEW|MODIFIED|REMOVED|STRUCTURAL|FORMATTING",
  "description": "1-2 sentence explanation of what changed",
  "old_text": "exact quote from old doc (max 300 chars, empty string if NEW)",
  "new_text": "exact quote from new doc (max 300 chars, empty string if REMOVED)",
  "impact": "LEVEL — explanation (CRITICAL/HIGH/MEDIUM/LOW)",
  "search_old": "unique 10-40 char snippet to find in old PDF",
  "search_new": "unique 10-40 char snippet to find in new PDF",
  "verification_status": "verified",
  "verification_conclusion": "brief summary",
  "verification_keywords": ["key", "terms"]
}

For FALSE_POSITIVE:
{"decision": "FALSE_POSITIVE", "reason": "brief explanation"}

For UNCERTAIN:
{"decision": "UNCERTAIN", "reason": "what's missing or unclear", \
"notes": "any partial observations that might help a follow-up pass"}

Categories:
- NEW: content in new but not old
- MODIFIED: content changed between versions
- REMOVED: content in old but not new
- STRUCTURAL: document structure changes (numbering, ordering, layout)
- FORMATTING: purely formatting changes (whitespace, line breaks, punctuation style) \
with no substantive content difference. Still save these.
"""


# ── PASS 2: Opus (deep analysis for uncertain candidates) ───────────

PASS2_SYSTEM_PROMPT = """\
You are making a FINAL determination on a document change that a previous pass \
could not confidently resolve.

You will receive:
1. The original candidate information
2. The previous analyst's notes on what was unclear
3. Extended page text (more pages of context)

The programmatic diff flagged this section as changed. Your job is to find and \
describe the change. It is almost certainly there — look carefully.

You MUST respond with a JSON object (no markdown fences):

If you find a change (expected in most cases):
{
  "decision": "SAVE",
  "section": "section ref",
  "title": "brief title",
  "category": "NEW|MODIFIED|REMOVED|STRUCTURAL|FORMATTING",
  "description": "1-2 sentence explanation",
  "old_text": "exact quote (max 300 chars, empty if NEW)",
  "new_text": "exact quote (max 300 chars, empty if REMOVED)",
  "impact": "LEVEL — explanation",
  "search_old": "unique 10-40 char snippet",
  "search_new": "unique 10-40 char snippet",
  "verification_status": "verified",
  "verification_conclusion": "brief summary",
  "verification_keywords": ["key", "terms"]
}

If truly no change exists (rare):
{"decision": "FALSE_POSITIVE", "reason": "detailed explanation"}
"""


def run_mini_agent_pass1(
    job_id: str,
    candidate: dict,
    page_cache: dict,
    api_key: str = "",
) -> dict:
    """
    Pass 1: Fast Sonnet triage of a single candidate.
    Single API call, no tools.

    Returns: {
        "agent_id": str,
        "decision": "SAVE" | "FALSE_POSITIVE" | "UNCERTAIN",
        "change": dict or None,  # populated if SAVE
        "notes": str,            # populated if UNCERTAIN (for pass 2)
        "reason": str,           # populated if FALSE_POSITIVE or UNCERTAIN
        "tokens_used": int,
        "error": str or None,
    }
    """
    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        return {"agent_id": candidate["id"], "decision": "UNCERTAIN",
                "change": None, "notes": "No API key", "reason": "No API key",
                "tokens_used": 0, "error": "No API key"}

    client = anthropic.Anthropic(api_key=effective_key)
    start = time.time()
    cand_id = candidate["id"]

    # Build user message with pre-extracted page text
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

    old_text_block = "\n\n".join(old_text_parts) if old_text_parts else ""
    new_text_block = "\n\n".join(new_text_parts) if new_text_parts else ""

    # Fall back to diff text previews
    old_preview = candidate.get("old_text_preview", "")
    new_preview = candidate.get("new_text_preview", "")
    if not old_text_block and old_preview:
        old_text_block = f"(from diff — first 800 chars of old section)\n{old_preview}"
    if not new_text_block and new_preview:
        new_text_block = f"(from diff — first 800 chars of new section)\n{new_preview}"

    if not old_text_block:
        old_text_block = "(no text available)"
    if not new_text_block:
        new_text_block = "(no text available)"

    user_msg = (
        f"## Candidate Change: {candidate['section']}\n\n"
        f"**Category hint**: {candidate['category_hint']}\n"
        f"**Diff preview**: {candidate.get('diff_preview', 'N/A')}\n"
    )
    if candidate.get("manifest_item"):
        user_msg += f"**Manifest entry**: {candidate['manifest_item']}\n"

    # Include diff text previews as reference
    if old_preview or new_preview:
        user_msg += f"\n### Diff Text Comparison (from programmatic diff)\n"
        if old_preview:
            user_msg += f"**Old section text (excerpt):**\n{old_preview[:500]}\n\n"
        if new_preview:
            user_msg += f"**New section text (excerpt):**\n{new_preview[:500]}\n\n"

    user_msg += (
        f"\n### Old Document Full Page Text\n{old_text_block}\n\n"
        f"### New Document Full Page Text\n{new_text_block}\n\n"
        f"Analyze this candidate and respond with your JSON decision."
    )

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,  # Sonnet
            max_tokens=2048,
            system=PASS1_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0,
        )
    except anthropic.RateLimitError:
        print(f"[pass1 {cand_id}] Rate limited, waiting 10s...")
        time.sleep(10)
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                system=PASS1_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0,
            )
        except Exception as e:
            print(f"[pass1 {cand_id}] Retry failed: {e}")
            return {"agent_id": cand_id, "decision": "UNCERTAIN",
                    "change": None, "notes": f"API error: {e}", "reason": str(e),
                    "tokens_used": 0, "error": str(e)}
    except Exception as e:
        print(f"[pass1 {cand_id}] API error: {e}")
        return {"agent_id": cand_id, "decision": "UNCERTAIN",
                "change": None, "notes": f"API error: {e}", "reason": str(e),
                "tokens_used": 0, "error": str(e)}

    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    text = response.content[0].text if response.content else "{}"
    elapsed = round(time.time() - start, 1)

    # Parse JSON response
    parsed = _parse_json_response(text)
    decision = parsed.get("decision", "UNCERTAIN").upper()

    if decision == "SAVE":
        change = {k: v for k, v in parsed.items() if k != "decision"}
        change["manifest_item"] = change.get("manifest_item") or candidate.get("manifest_item", "")
        print(f"[pass1 {cand_id}] SAVE in {elapsed}s, {tokens_used} tokens — {change.get('title', '')[:60]}")
        return {"agent_id": cand_id, "decision": "SAVE",
                "change": change, "notes": "", "reason": "",
                "tokens_used": tokens_used, "error": None}

    elif decision == "FALSE_POSITIVE":
        reason = parsed.get("reason", "No reason given")
        print(f"[pass1 {cand_id}] FALSE_POSITIVE in {elapsed}s, {tokens_used} tokens — {reason[:80]}")
        return {"agent_id": cand_id, "decision": "FALSE_POSITIVE",
                "change": None, "notes": "", "reason": reason,
                "tokens_used": tokens_used, "error": None}

    else:  # UNCERTAIN or unparseable
        notes = parsed.get("notes", "")
        reason = parsed.get("reason", "Could not determine change from provided context")
        print(f"[pass1 {cand_id}] UNCERTAIN in {elapsed}s, {tokens_used} tokens — {reason[:80]}")
        return {"agent_id": cand_id, "decision": "UNCERTAIN",
                "change": None, "notes": notes, "reason": reason,
                "tokens_used": tokens_used, "error": None}


def run_mini_agent_pass2(
    job_id: str,
    candidate: dict,
    pass1_result: dict,
    page_cache: dict,
    old_pdf_path: str,
    new_pdf_path: str,
    old_page_count: int,
    new_page_count: int,
    api_key: str = "",
) -> dict:
    """
    Pass 2: Opus deep analysis for candidates that Pass 1 couldn't resolve.
    Gets extended context (more surrounding pages) and Sonnet's notes.
    Single API call, no tools.

    Returns: {
        "agent_id": str,
        "change": dict or None,
        "tokens_used": int,
        "error": str or None,
    }
    """
    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        return {"agent_id": candidate["id"], "change": None,
                "tokens_used": 0, "error": "No API key"}

    client = anthropic.Anthropic(api_key=effective_key)
    start = time.time()
    cand_id = candidate["id"]

    # Build EXTENDED context — more pages around the candidate
    old_pages_base = candidate.get("old_pages", [])
    new_pages_base = candidate.get("new_pages", [])

    # Expand page range: 2 pages before and 2 after each referenced page
    old_pages_extended = _expand_page_range(old_pages_base, old_page_count, margin=2)
    new_pages_extended = _expand_page_range(new_pages_base, new_page_count, margin=2)

    old_text_parts = []
    for page in old_pages_extended:
        text = page_cache.get(("old", page), "")
        if not text:
            # Extract on-demand for pages not in cache
            try:
                result = extract_page_text(old_pdf_path, page)
                text = result.get("text", "")
            except Exception:
                text = ""
        if text:
            old_text_parts.append(f"--- OLD Page {page} ---\n{text}")

    new_text_parts = []
    for page in new_pages_extended:
        text = page_cache.get(("new", page), "")
        if not text:
            try:
                result = extract_page_text(new_pdf_path, page)
                text = result.get("text", "")
            except Exception:
                text = ""
        if text:
            new_text_parts.append(f"--- NEW Page {page} ---\n{text}")

    old_text_block = "\n\n".join(old_text_parts) if old_text_parts else "(no text available)"
    new_text_block = "\n\n".join(new_text_parts) if new_text_parts else "(no text available)"

    # Include diff previews as additional signal
    old_preview = candidate.get("old_text_preview", "")
    new_preview = candidate.get("new_text_preview", "")

    sonnet_notes = pass1_result.get("notes", "")
    sonnet_reason = pass1_result.get("reason", "")

    user_msg = (
        f"## Candidate Change: {candidate['section']}\n\n"
        f"**Category hint**: {candidate['category_hint']}\n"
        f"**Diff preview**: {candidate.get('diff_preview', 'N/A')}\n"
    )
    if candidate.get("manifest_item"):
        user_msg += f"**Manifest entry**: {candidate['manifest_item']}\n"

    user_msg += (
        f"\n### Previous Analyst Notes\n"
        f"The first-pass analyst marked this as UNCERTAIN.\n"
        f"**Reason**: {sonnet_reason}\n"
        f"**Notes**: {sonnet_notes}\n"
    )

    if old_preview or new_preview:
        user_msg += f"\n### Diff Text Comparison (from programmatic diff)\n"
        if old_preview:
            user_msg += f"**Old section text (excerpt):**\n{old_preview[:800]}\n\n"
        if new_preview:
            user_msg += f"**New section text (excerpt):**\n{new_preview[:800]}\n\n"

    user_msg += (
        f"\n### Old Document Extended Page Text (pages {old_pages_extended})\n{old_text_block}\n\n"
        f"### New Document Extended Page Text (pages {new_pages_extended})\n{new_text_block}\n\n"
        f"Find the change and respond with your JSON decision. "
        f"The diff flagged this section — the change is almost certainly there."
    )

    try:
        response = client.messages.create(
            model="claude-opus-4-6",  # Opus for deep analysis
            max_tokens=2048,
            system=PASS2_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            temperature=0,
        )
    except anthropic.RateLimitError:
        print(f"[pass2 {cand_id}] Rate limited, waiting 15s...")
        time.sleep(15)
        try:
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2048,
                system=PASS2_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                temperature=0,
            )
        except Exception as e:
            print(f"[pass2 {cand_id}] Retry failed: {e}")
            return {"agent_id": cand_id, "change": None,
                    "tokens_used": 0, "error": str(e)}
    except Exception as e:
        print(f"[pass2 {cand_id}] API error: {e}")
        return {"agent_id": cand_id, "change": None,
                "tokens_used": 0, "error": str(e)}

    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    text = response.content[0].text if response.content else "{}"
    elapsed = round(time.time() - start, 1)

    parsed = _parse_json_response(text)
    decision = parsed.get("decision", "FALSE_POSITIVE").upper()

    if decision == "SAVE":
        change = {k: v for k, v in parsed.items() if k != "decision"}
        change["manifest_item"] = change.get("manifest_item") or candidate.get("manifest_item", "")
        print(f"[pass2 {cand_id}] SAVE in {elapsed}s, {tokens_used} tokens — {change.get('title', '')[:60]}")
        return {"agent_id": cand_id, "change": change,
                "tokens_used": tokens_used, "error": None}
    else:
        reason = parsed.get("reason", "No change found")
        print(f"[pass2 {cand_id}] REJECTED in {elapsed}s, {tokens_used} tokens — {reason[:80]}")
        return {"agent_id": cand_id, "change": None,
                "tokens_used": tokens_used, "error": None}


# ── Helpers ──────────────────────────────────────────────────────────

def _expand_page_range(base_pages: list[int], total_pages: int, margin: int = 2) -> list[int]:
    """Expand a list of page numbers by adding surrounding pages."""
    if not base_pages:
        return []
    all_pages = set()
    for p in base_pages:
        for offset in range(-margin, margin + 1):
            candidate = p + offset
            if 1 <= candidate <= total_pages:
                all_pages.add(candidate)
    return sorted(all_pages)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from model response, handling markdown fences and extra text."""
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    import re
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    print(f"[mini-agent] Failed to parse JSON response: {text[:200]}...")
    return {"decision": "UNCERTAIN", "reason": "Failed to parse model response", "notes": text[:500]}
