"""
Claude agent orchestrator. Runs an agentic tool-calling loop to
analyze two PDFs and produce a verified change register.
"""
import asyncio
import json
import time
import os
import anthropic
from datetime import datetime
from typing import AsyncGenerator

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .tools import TOOL_DEFINITIONS, execute_tool
from .pdf_utils import annotate_pdf
from .models import ChangeItem, ProgressEvent

SYSTEM_PROMPT = """\
You are a PDF document comparison analyst. You compare two versions of a document \
and produce a comprehensive, verified change register.

You have tools to extract text, detect structure, search, and diff the documents. \
Use them extensively to be thorough.

## Your Process

1. **Extract & Understand**: Extract text from both PDFs. Understand what kind of \
documents these are (standards, specs, contracts, policies, etc.).

2. **Detect Manifest**: Check if either document contains a revision history, change \
log, or manifest of changes. If found, use it as your ground-truth checklist.

3. **Parse Structure**: Detect section headings and structure in both documents. \
Check if sections were renumbered between versions.

4. **Systematic Diff**: Run section-by-section diffs. Identify every substantive change.

5. **Classify & Describe**: For each change, determine:
   - Category: NEW (content that didn't exist before), MODIFIED (changed content), \
REMOVED (content that was deleted), STRUCTURAL (reorganization/renumbering)
   - A clear title (what changed)
   - A description (why it matters)
   - The exact old text and new text

6. **Verify**: For NEW items, search the old document to confirm the concept truly \
doesn't exist elsewhere. For REMOVED items, search the new document to confirm no \
traces remain. Record what you searched and what you found.

7. **Assess Impact**: Rate each change: CRITICAL (changes pass/fail criteria or core \
requirements), HIGH (significant new requirements or scope changes), MEDIUM (process \
or reference updates), LOW (editorial, formatting, numbering).

8. **Submit**: Call submit_changes with your complete register.

## Important Rules
- Report progress frequently using report_progress so the user can see what you're doing.
- Be thorough — check the ENTIRE document, don't just spot-check.
- For verification, record the keywords you searched and the conclusion.
- Include search_old and search_new snippets (short text to find in each PDF for highlighting).
- If a manifest exists, verify you've covered every item in it.
- Don't hallucinate changes — only report what you actually found in the diffs.
"""

MAX_AGENT_TURNS = 30


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

    client = anthropic.Anthropic(api_key=effective_key)

    job_context = {
        "old_pdf_path": old_pdf_path,
        "new_pdf_path": new_pdf_path,
        "submitted_changes": None,
        "submitted_manifest": None,
    }

    async def emit(stage, percent, message):
        if progress_callback:
            await progress_callback(ProgressEvent(
                stage=stage, percent=percent, message=message,
                timestamp=datetime.utcnow().isoformat(),
            ))

    await emit("starting", 0, "Starting analysis...")

    # Build initial user message
    user_msg = (
        f"Compare these two PDF documents and produce a complete change register.\n\n"
        f"**Old version**: '{old_label}' — uploaded as 'old' PDF\n"
        f"**New version**: '{new_label}' — uploaded as 'new' PDF\n\n"
        f"Be thorough. Extract text, detect structure and any revision history, "
        f"run systematic diffs, classify every change, verify NEW and REMOVED items, "
        f"assess impact, and submit the complete register."
    )

    messages = [{"role": "user", "content": user_msg}]

    for turn in range(MAX_AGENT_TURNS):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
        except Exception as e:
            await emit("error", 0, f"Claude API error: {str(e)}")
            raise

        # Process response
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check if there are any tool_use blocks that need responses
        tool_use_blocks = [b for b in assistant_content if b.type == "tool_use"]

        if not tool_use_blocks:
            # No tools called — agent is done
            await emit("agent_done", 85, "Agent finished analysis")
            break

        # Process ALL tool calls and return results together
        tool_results = []
        for block in tool_use_blocks:
            tool_name = block.name
            tool_input = block.input

            # Handle progress reporting
            if tool_name == "report_progress":
                await emit(
                    tool_input.get("stage", "working"),
                    tool_input.get("percent", 0),
                    tool_input.get("message", ""),
                )
                result_str = json.dumps({"status": "reported"})
            else:
                result_str = execute_tool(tool_name, tool_input, job_context)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

        # If stop_reason was end_turn but had tool calls, we processed them above
        # and will continue the loop. If no more tools needed, next turn will break.

    # Post-process: build annotated PDFs
    await emit("annotating", 88, "Generating annotated PDFs...")

    changes = job_context.get("submitted_changes") or []
    manifest_data = job_context.get("submitted_manifest")

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

    await emit("annotating", 95, f"Annotated {old_result['highlights']} + {new_result['highlights']} passages")

    # Build final change items with page numbers
    final_changes = []
    for i, c in enumerate(changes):
        impact_level = c.get("impact", "MEDIUM").split(" ")[0].split("—")[0].strip()
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
            impact=c.get("impact", "MEDIUM"),
            impact_level=impact_level,
            manifest_item=c.get("manifest_item"),
            verification_status=c.get("verification_status"),
            verification_conclusion=c.get("verification_conclusion"),
            verification_keywords=c.get("verification_keywords", []),
            old_page=old_result["page_map"].get(i + 1),
            new_page=new_result["page_map"].get(i + 1),
        ))

    # Compute summary
    by_category = {}
    by_impact = {}
    for c in final_changes:
        by_category[c.category] = by_category.get(c.category, 0) + 1
        by_impact[c.impact_level] = by_impact.get(c.impact_level, 0) + 1

    await emit("complete", 100, f"Analysis complete: {len(final_changes)} changes found")

    return {
        "changes": [c.model_dump() for c in final_changes],
        "total_changes": len(final_changes),
        "by_category": by_category,
        "by_impact": by_impact,
        "manifest": manifest_data,
        "old_annotated_path": old_ann_path,
        "new_annotated_path": new_ann_path,
    }
