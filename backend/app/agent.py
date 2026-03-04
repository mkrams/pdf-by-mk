"""
Claude agent orchestrator. Runs an agentic tool-calling loop to
analyze two PDFs and produce a verified change register.

Uses the SYNC Anthropic client — this runs in a worker thread
so it doesn't block the FastAPI event loop.
"""
import json
import time
import os
import traceback
import anthropic
from datetime import datetime

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .tools import TOOL_DEFINITIONS, execute_tool
from .pdf_utils import annotate_pdf
from .models import ChangeItem, ProgressEvent

SYSTEM_PROMPT = """\
You are a thorough PDF document comparison analyst. Compare two document versions \
and produce a COMPLETE verified change register. Missing changes is unacceptable.

## CRITICAL RULE: MANIFEST COMPLETENESS
If the document contains a revision history / change manifest listing what was \
revised, added, or deleted — you MUST cover 100% of those items. Every single \
section, table, appendix, and figure mentioned in the manifest MUST appear as a \
change in your output. The manifest is your checklist. After building your change \
list, cross-check it against the manifest and add any missing items.

## Efficiency Rules
- Call multiple tools in parallel whenever possible (e.g. extract both PDFs at once).
- Use detect_document_structure and detect_revision_history first.
- Use diff_sections for systematic comparison.
- You have a MAXIMUM of 20 turns. Be thorough within this budget.
- **Adaptive page batching**: Adjust how many pages you read per turn based on content \
complexity. For simple/boilerplate sections (formatting, headers, editorial changes), \
batch 8-12 pages per turn. For dense/complex content (tables with data, sections \
flagged in the manifest, numerical specifications), read only 2-4 pages per turn so \
you can analyze carefully. Re-evaluate after each turn based on what you found.
- Report progress every 2-3 tool calls.

## Process

1. **Structure + Manifest** (parallel, turn 1): Call detect_document_structure on \
both PDFs + detect_revision_history on BOTH PDFs — all in one turn.

2. **Diff**: Run diff_sections to get all section-level changes.

3. **Read targeted pages** (use adaptive batching): Read pages where diffs were found \
AND pages containing every item mentioned in the manifest. Batch aggressively for \
boilerplate sections, slow down for tables and manifest-flagged content.

4. **Classify each change**: category (NEW/MODIFIED/REMOVED/STRUCTURAL), \
title, description, old_text, new_text, impact.

5. **Manifest cross-check** (CRITICAL): Before submitting, compare your change list \
against the manifest. For every manifest item you haven't yet covered, read the \
relevant pages and add the change. Do NOT skip this step.

6. **Submit**: Call submit_changes with ALL changes.

## What Counts as a Change
- Any text modification, no matter how small (wording, values, references)
- Structural changes to tables (new rows, columns, reorganization)
- New content added (sections, notes, figures, table entries)
- Content removed or deleted
- Changes to table structure, headers, or organization
- Changes to appendices, figures, and legends
- Reference updates (standards, document numbers)

## Impact Levels
- CRITICAL: changes pass/fail criteria or core requirements
- HIGH: significant new requirements or scope changes
- MEDIUM: process or reference updates
- LOW: editorial, formatting, numbering

## Required Fields per Change
section, title, category, description, old_text, new_text, impact, \
verification_status, verification_conclusion, verification_keywords, \
search_old (snippet for annotation), search_new (snippet for annotation)
"""

MAX_AGENT_TURNS = 20
JOB_TIMEOUT_SECONDS = 420  # 7 minute hard timeout
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds to wait between retries


def _describe_tools(tool_names: list[str], blocks: list) -> str:
    """Convert raw tool names into a natural-language progress message."""
    from collections import Counter

    counts = Counter(tool_names)
    parts = []

    for name, n in counts.items():
        if name == "extract_pdf_text":
            parts.append("Reading full document text" if n == 1 else "Reading both documents")
        elif name == "extract_pdf_page":
            # Collect page details from blocks
            page_refs = []
            for b in blocks:
                if b.name == "extract_pdf_page" and isinstance(b.input, dict):
                    pg = b.input.get("page_number", "?")
                    which = b.input.get("pdf_id", "")
                    page_refs.append(f"p{pg} ({which})")
            if page_refs:
                if len(page_refs) <= 3:
                    parts.append(f"Reading {', '.join(page_refs)}")
                else:
                    parts.append(f"Deep-reading {n} pages: {', '.join(page_refs[:3])}...")
            else:
                parts.append(f"Reading {n} page(s)")
        elif name == "detect_document_structure":
            parts.append("Mapping document structure" if n == 1 else "Mapping both document structures")
        elif name == "detect_revision_history":
            parts.append("Scanning for revision history & change manifest")
        elif name == "search_document":
            # Get what we're searching for
            queries = []
            for b in blocks:
                if b.name == "search_document" and isinstance(b.input, dict):
                    q = b.input.get("query", "")
                    if q:
                        queries.append(q[:30])
            if queries and len(queries) <= 2:
                parts.append(f"Searching for: {', '.join(queries)}")
            else:
                parts.append(f"Running {n} verification searches")
        elif name == "diff_sections":
            parts.append("Comparing sections side-by-side")
        elif name == "submit_changes":
            parts.append("Compiling the final change register")
        else:
            parts.append(name)

    if not parts:
        return "Processing..."

    return " · ".join(parts)


def _call_claude_with_retry(client, model, system, tools, messages, max_tokens):
    """Call Claude API with retry on rate limits and transient errors."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                temperature=0,  # Deterministic: same docs → same results
            )
        except anthropic.RateLimitError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"[agent] Rate limited, retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                raise
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < MAX_RETRIES - 1:
                last_error = e
                wait = RETRY_BACKOFF[attempt]
                print(f"[agent] Server error {e.status_code}, retrying in {wait}s")
                time.sleep(wait)
            else:
                raise
    raise last_error


def run_analysis(
    job_id: str,
    old_pdf_path: str,
    new_pdf_path: str,
    old_label: str,
    new_label: str,
    api_key: str = "",
    progress_callback=None,
) -> dict:
    """
    Run the full agentic analysis pipeline.

    This is a SYNC function — it blocks while calling the Claude API.
    The caller should run it in a thread (asyncio.to_thread) to avoid
    blocking the event loop.

    progress_callback: a sync callable(ProgressEvent) -> None
    """

    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        raise ValueError("No Anthropic API key provided")

    client = anthropic.Anthropic(api_key=effective_key)

    job_context = {
        "old_pdf_path": old_pdf_path,
        "new_pdf_path": new_pdf_path,
        "submitted_changes": None,
        "submitted_manifest": None,
    }

    start_time = time.time()
    total_input_tokens = 0
    total_output_tokens = 0

    def emit(stage, percent, message, turn=0):
        if progress_callback:
            elapsed_secs = int(time.time() - start_time)
            progress_callback(ProgressEvent(
                stage=stage,
                percent=percent,
                message=message,
                turn=turn,
                max_turns=MAX_AGENT_TURNS,
                tokens=total_input_tokens + total_output_tokens,
                elapsed=elapsed_secs,
                timestamp=datetime.utcnow().isoformat(),
            ))

    emit("starting", 0, "Starting analysis...", 0)
    print(f"[job {job_id}] Starting analysis: old='{old_label}', new='{new_label}'")

    # Build initial user message
    user_msg = (
        f"Compare these two PDF documents and produce a COMPLETE change register.\n\n"
        f"**Old version**: '{old_label}' — uploaded as 'old' PDF\n"
        f"**New version**: '{new_label}' — uploaded as 'new' PDF\n\n"
        f"IMPORTANT: If the document contains a revision history or change manifest, "
        f"you MUST capture every single item listed there. Missing manifest items is "
        f"a critical failure. Start by detecting structure and revision history on "
        f"both documents in parallel. Then diff, read all relevant pages (especially "
        f"tables), classify, cross-check against manifest, and submit."
    )

    messages = [{"role": "user", "content": user_msg}]

    for turn in range(MAX_AGENT_TURNS):
        turn_num = turn + 1

        # Hard timeout check
        if time.time() - start_time > JOB_TIMEOUT_SECONDS:
            emit("timeout", 80, "Timeout reached — finalizing with current data", turn_num)
            print(f"[job {job_id}] Timeout at turn {turn_num}")
            break

        try:
            response = _call_claude_with_retry(
                client, CLAUDE_MODEL, SYSTEM_PROMPT,
                TOOL_DEFINITIONS, messages, 16384,
            )
        except anthropic.RateLimitError as e:
            emit("rate_limited", 0,
                f"Rate limited after {MAX_RETRIES} retries. Try again in a minute.", turn_num)
            raise
        except Exception as e:
            emit("error", 0, f"Claude API error: {str(e)}", turn_num)
            raise

        # Track tokens
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Process response
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Log what Claude returned
        block_types = [f"{b.type}({b.name})" if b.type == "tool_use" else b.type for b in assistant_content]
        print(f"[job {job_id}] Turn {turn_num}: stop={response.stop_reason}, blocks={block_types}")

        # Check for tool_use blocks
        tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_use_blocks:
            pct = min(85, int(turn_num / MAX_AGENT_TURNS * 85))
            emit("agent_done", pct, "Agent finished analysis", turn_num)
            print(f"[job {job_id}] Agent done at turn {turn_num} (no tool_use blocks)")
            break

        # Process ALL tool calls
        tool_results = []
        tool_names = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input
            tool_names.append(tool_name)

            if tool_name == "submit_changes":
                print(f"[job {job_id}] submit_changes: input type={type(tool_input).__name__}, "
                      f"has 'changes' key={isinstance(tool_input, dict) and 'changes' in tool_input}")

            if tool_name == "report_progress":
                result_str = json.dumps({"status": "reported"})
            else:
                result_str = execute_tool(tool_name, tool_input, job_context)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

        # Emit progress with natural-language descriptions
        pct = min(80, int(turn_num / MAX_AGENT_TURNS * 80))
        real_tools = [t for t in tool_names if t != "report_progress"]
        if real_tools:
            msg = _describe_tools(real_tools, tool_use_blocks)
            emit("working", pct, msg, turn_num)

    # ── Post-process ──────────────────────────────────────────────
    emit("annotating", 88, "Generating annotated PDFs...", MAX_AGENT_TURNS)

    raw_changes = job_context.get("submitted_changes")
    manifest_data = job_context.get("submitted_manifest")

    print(f"[job {job_id}] Post-processing: submitted_changes={type(raw_changes).__name__}, "
          f"count={len(raw_changes) if isinstance(raw_changes, list) else 'N/A'}")

    if raw_changes is None:
        print(f"[job {job_id}] WARNING: Agent never called submit_changes!")
        raw_changes = []

    if not isinstance(raw_changes, list):
        print(f"[job {job_id}] WARNING: submitted_changes is {type(raw_changes).__name__}")
        raw_changes = []

    changes = [c for c in raw_changes if isinstance(c, dict)]
    if len(changes) != len(raw_changes):
        print(f"[job {job_id}] WARNING: filtered {len(raw_changes) - len(changes)} non-dict changes")

    print(f"[job {job_id}] Building annotations for {len(changes)} changes")

    # Build annotation data
    old_annotations = []
    new_annotations = []
    for i, c in enumerate(changes):
        if c.get("search_old"):
            old_annotations.append({"change_id": i + 1, "search_text": c["search_old"]})
        if c.get("search_new"):
            new_annotations.append({"change_id": i + 1, "search_text": c["search_new"]})

    # Generate annotated PDFs
    job_dir = os.path.dirname(old_pdf_path)
    old_ann_path = os.path.join(job_dir, "old_annotated.pdf")
    new_ann_path = os.path.join(job_dir, "new_annotated.pdf")

    old_result = annotate_pdf(old_pdf_path, old_ann_path, old_annotations)
    new_result = annotate_pdf(new_pdf_path, new_ann_path, new_annotations)

    emit("annotating", 95,
        f"Annotated {old_result['highlights']} + {new_result['highlights']} passages",
        MAX_AGENT_TURNS)

    # Build final change items
    final_changes = []
    for i, c in enumerate(changes):
        try:
            impact_raw = c.get("impact", "MEDIUM") or "MEDIUM"
            impact_level = impact_raw.split(" ")[0].split("\u2014")[0].strip()
            if impact_level not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                impact_level = "MEDIUM"

            final_changes.append(ChangeItem(
                id=i + 1,
                section=c.get("section", ""),
                title=c.get("title", ""),
                category=c.get("category", "MODIFIED"),
                description=c.get("description", ""),
                old_text=c.get("old_text"),
                new_text=c.get("new_text"),
                impact=impact_raw,
                impact_level=impact_level,
                manifest_item=c.get("manifest_item"),
                verification_status=c.get("verification_status"),
                verification_conclusion=c.get("verification_conclusion"),
                verification_keywords=c.get("verification_keywords", []),
                old_page=old_result["page_map"].get(i + 1),
                new_page=new_result["page_map"].get(i + 1),
            ))
        except Exception as e:
            print(f"[job {job_id}] Skipping malformed change #{i+1}: {e}")
            continue

    # Compute summary
    by_category = {}
    by_impact = {}
    for c in final_changes:
        by_category[c.category] = by_category.get(c.category, 0) + 1
        by_impact[c.impact_level] = by_impact.get(c.impact_level, 0) + 1

    elapsed = int(time.time() - start_time)
    mins, secs = divmod(elapsed, 60)
    print(f"[job {job_id}] COMPLETE: {len(final_changes)} changes in {mins}:{secs:02d}, "
          f"{total_input_tokens + total_output_tokens:,} tokens")

    emit("complete", 100,
        f"Done in {mins}:{secs:02d} — {len(final_changes)} changes, "
        f"{total_input_tokens + total_output_tokens:,} tokens",
        MAX_AGENT_TURNS)

    return {
        "changes": [c.model_dump() for c in final_changes],
        "total_changes": len(final_changes),
        "by_category": by_category,
        "by_impact": by_impact,
        "manifest": manifest_data,
        "old_annotated_path": old_ann_path,
        "new_annotated_path": new_ann_path,
    }
