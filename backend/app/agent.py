"""
Claude agent orchestrator. Runs an agentic tool-calling loop to
analyze two PDFs and produce a verified change register.

Uses AsyncAnthropic so all I/O is non-blocking and the FastAPI
event loop stays responsive (SSE, health checks, etc.).
"""
import asyncio
import json
import time
import os
import traceback
import anthropic
from datetime import datetime
from typing import AsyncGenerator

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .tools import TOOL_DEFINITIONS, execute_tool
from .pdf_utils import annotate_pdf
from .models import ChangeItem, ProgressEvent

SYSTEM_PROMPT = """\
You are a fast, efficient PDF document comparison analyst. Compare two document \
versions and produce a verified change register.

## SPEED RULES (CRITICAL)
- Call multiple tools in parallel whenever possible (e.g. extract both PDFs at once).
- Do NOT extract full text of both documents — use detect_document_structure and \
detect_revision_history first, then use targeted page reads and search.
- Use diff_sections for systematic comparison instead of reading every page.
- Limit verification searches to 2-3 key terms per NEW/REMOVED item — don't over-search.
- Submit your changes as soon as you have them. Don't do unnecessary extra passes.
- You have a MAXIMUM of 15 turns. Be efficient.
- Report progress every 2-3 tool calls.

## Process (be fast)

1. **Structure + Manifest** (parallel): Call detect_document_structure on both + \
detect_revision_history on the new PDF — all in one turn.

2. **Diff**: Run diff_sections to get all changes at once.

3. **Read targeted pages**: Only read specific pages where diffs were found.

4. **Classify**: For each change — category (NEW/MODIFIED/REMOVED/STRUCTURAL), \
title, description, old_text, new_text, impact level.

5. **Quick verify**: For NEW items, one search in old doc. For REMOVED, one search \
in new doc. Batch multiple searches in parallel.

6. **Submit**: Call submit_changes immediately.

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

MAX_AGENT_TURNS = 15
JOB_TIMEOUT_SECONDS = 300  # 5 minute hard timeout
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]  # seconds to wait between retries


async def _call_claude_with_retry(client, model, system, tools, messages, max_tokens):
    """Call Claude API with automatic retry on rate limits and transient errors.

    Uses the async client so we don't block the event loop.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )
        except anthropic.RateLimitError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"[agent] Rate limited, retrying in {wait}s (attempt {attempt+1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
            else:
                raise
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < MAX_RETRIES - 1:
                last_error = e
                wait = RETRY_BACKOFF[attempt]
                print(f"[agent] Server error {e.status_code}, retrying in {wait}s")
                await asyncio.sleep(wait)
            else:
                raise
    raise last_error


async def run_analysis(
    job_id: str,
    old_pdf_path: str,
    new_pdf_path: str,
    old_label: str,
    new_label: str,
    api_key: str = "",
    progress_callback=None,
) -> dict:
    """Run the full agentic analysis pipeline."""

    effective_key = api_key or ANTHROPIC_API_KEY
    if not effective_key:
        raise ValueError("No Anthropic API key provided")

    # Use AsyncAnthropic so API calls don't block the event loop
    client = anthropic.AsyncAnthropic(api_key=effective_key)

    job_context = {
        "old_pdf_path": old_pdf_path,
        "new_pdf_path": new_pdf_path,
        "submitted_changes": None,
        "submitted_manifest": None,
    }

    start_time = time.time()
    total_input_tokens = 0
    total_output_tokens = 0

    async def emit(stage, percent, message, turn=0):
        if progress_callback:
            elapsed = int(time.time() - start_time)
            mins, secs = divmod(elapsed, 60)
            detail = (
                f"[{mins}:{secs:02d}] Turn {turn}/{MAX_AGENT_TURNS} | "
                f"{total_input_tokens + total_output_tokens:,} tokens | {message}"
            )
            await progress_callback(ProgressEvent(
                stage=stage, percent=percent, message=detail,
                timestamp=datetime.utcnow().isoformat(),
            ))

    await emit("starting", 0, "Starting analysis...", 0)
    print(f"[job {job_id}] Starting analysis: old='{old_label}', new='{new_label}'")

    # Build initial user message
    user_msg = (
        f"Compare these two PDF documents and produce a complete change register.\n\n"
        f"**Old version**: '{old_label}' — uploaded as 'old' PDF\n"
        f"**New version**: '{new_label}' — uploaded as 'new' PDF\n\n"
        f"Be fast and efficient. Start by detecting structure and revision history "
        f"in parallel. Then diff, classify, verify, and submit."
    )

    messages = [{"role": "user", "content": user_msg}]

    for turn in range(MAX_AGENT_TURNS):
        turn_num = turn + 1

        # Hard timeout check
        if time.time() - start_time > JOB_TIMEOUT_SECONDS:
            await emit("timeout", 80, "Timeout reached — finalizing with current data", turn_num)
            print(f"[job {job_id}] Timeout at turn {turn_num}")
            break

        try:
            response = await _call_claude_with_retry(
                client, CLAUDE_MODEL, SYSTEM_PROMPT,
                TOOL_DEFINITIONS, messages, 16384,
            )
        except anthropic.RateLimitError as e:
            await emit("rate_limited", 0,
                f"Rate limited after {MAX_RETRIES} retries. Try again in a minute.", turn_num)
            raise
        except Exception as e:
            await emit("error", 0, f"Claude API error: {str(e)}", turn_num)
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

        # Check if there are any tool_use blocks that need responses
        tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_use_blocks:
            pct = min(85, int(turn_num / MAX_AGENT_TURNS * 85))
            await emit("agent_done", pct, "Agent finished analysis", turn_num)
            print(f"[job {job_id}] Agent done at turn {turn_num} (no tool_use blocks)")
            break

        # Process ALL tool calls and return results together
        tool_results = []
        tool_names = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input
            tool_names.append(tool_name)

            # Log raw tool_input type for debugging
            if tool_name == "submit_changes":
                changes_val = tool_input.get("changes", "MISSING") if isinstance(tool_input, dict) else f"INPUT_NOT_DICT({type(tool_input).__name__})"
                change_count = len(changes_val) if isinstance(changes_val, list) else str(changes_val)[:100]
                print(f"[job {job_id}] submit_changes called: input_type={type(tool_input).__name__}, changes={change_count}")

            # Defensive: ensure tool_input is a dict
            if isinstance(tool_input, str):
                print(f"[job {job_id}] WARNING: tool_input for {tool_name} is str, parsing JSON")
                try:
                    tool_input = json.loads(tool_input)
                except (json.JSONDecodeError, TypeError):
                    tool_input = {}
            if not isinstance(tool_input, dict):
                print(f"[job {job_id}] WARNING: tool_input for {tool_name} is {type(tool_input).__name__}, defaulting to empty dict")
                tool_input = {}

            if tool_name == "report_progress":
                result_str = json.dumps({"status": "reported"})
            elif tool_name == "submit_changes":
                # Run submit_changes directly (not in thread) since it just stores data
                # This avoids any thread-safety concerns with job_context mutation
                result_str = execute_tool(tool_name, tool_input, job_context)
                print(f"[job {job_id}] submit_changes result: {result_str}")
                print(f"[job {job_id}] job_context submitted_changes type={type(job_context.get('submitted_changes')).__name__}, len={len(job_context.get('submitted_changes') or [])}")
            else:
                # CPU-bound PDF operations — run in thread
                result_str = await asyncio.to_thread(
                    execute_tool, tool_name, tool_input, job_context
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

        # Emit progress with tool names
        pct = min(80, int(turn_num / MAX_AGENT_TURNS * 80))
        tools_str = ", ".join(t for t in tool_names if t != "report_progress")
        if tools_str:
            await emit("working", pct, f"Called: {tools_str}", turn_num)

    # Post-process: build annotated PDFs
    await emit("annotating", 88, "Generating annotated PDFs...", MAX_AGENT_TURNS)

    raw_changes = job_context.get("submitted_changes")
    manifest_data = job_context.get("submitted_manifest")

    print(f"[job {job_id}] Post-processing: submitted_changes type={type(raw_changes).__name__}, value={repr(raw_changes)[:300] if raw_changes else 'None'}")

    # Handle case where agent never called submit_changes
    if raw_changes is None:
        print(f"[job {job_id}] WARNING: Agent never called submit_changes!")
        raw_changes = []

    # Defensive: ensure changes is a list of dicts
    if isinstance(raw_changes, str):
        print(f"[job {job_id}] WARNING: submitted_changes is a string, parsing JSON")
        try:
            raw_changes = json.loads(raw_changes)
        except (json.JSONDecodeError, TypeError):
            raw_changes = []
    if not isinstance(raw_changes, list):
        print(f"[job {job_id}] WARNING: submitted_changes is {type(raw_changes).__name__}, defaulting to []")
        raw_changes = []

    # Validate each change is a dict
    changes = []
    for i, c in enumerate(raw_changes):
        if isinstance(c, dict):
            changes.append(c)
        else:
            print(f"[job {job_id}] WARNING: change #{i} is {type(c).__name__}, not dict: {repr(c)[:100]}")

    print(f"[job {job_id}] Validated {len(changes)} changes out of {len(raw_changes)} raw items")

    # Build annotation data
    old_annotations = []
    new_annotations = []
    for i, c in enumerate(changes):
        search_old = c.get("search_old")
        search_new = c.get("search_new")
        if search_old:
            old_annotations.append({"change_id": i + 1, "search_text": search_old})
        if search_new:
            new_annotations.append({"change_id": i + 1, "search_text": search_new})

    # Generate annotated PDFs in threads (CPU-bound)
    job_dir = os.path.dirname(old_pdf_path)
    old_ann_path = os.path.join(job_dir, "old_annotated.pdf")
    new_ann_path = os.path.join(job_dir, "new_annotated.pdf")

    old_result = await asyncio.to_thread(annotate_pdf, old_pdf_path, old_ann_path, old_annotations)
    new_result = await asyncio.to_thread(annotate_pdf, new_pdf_path, new_ann_path, new_annotations)

    await emit("annotating", 95,
        f"Annotated {old_result['highlights']} + {new_result['highlights']} passages",
        MAX_AGENT_TURNS)

    # Build final change items with page numbers
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
            print(f"[agent] Warning: skipping malformed change #{i+1}: {e}")
            print(f"[agent] Change data type={type(c).__name__}, repr={repr(c)[:200]}")
            continue

    # Compute summary
    by_category = {}
    by_impact = {}
    for c in final_changes:
        by_category[c.category] = by_category.get(c.category, 0) + 1
        by_impact[c.impact_level] = by_impact.get(c.impact_level, 0) + 1

    elapsed = int(time.time() - start_time)
    mins, secs = divmod(elapsed, 60)
    print(f"[job {job_id}] COMPLETE: {len(final_changes)} changes in {mins}:{secs:02d}, {total_input_tokens + total_output_tokens:,} tokens")

    await emit("complete", 100,
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
