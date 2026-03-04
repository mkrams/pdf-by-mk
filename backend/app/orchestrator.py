"""
Phase 1: Orchestrator — identifies candidate changes quickly using
programmatic diff + manifest detection, then optionally validates
with 1-2 Claude turns.

This runs synchronously in a worker thread.
"""
import json
import re
import time
import anthropic
from datetime import datetime
from collections import Counter

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from .pdf_utils import (
    detect_sections,
    detect_revision_history,
    diff_sections,
    extract_page_text,
)
from .models import ProgressEvent


def run_orchestrator(
    job_id: str,
    old_pdf_path: str,
    new_pdf_path: str,
    old_label: str,
    new_label: str,
    api_key: str = "",
    progress_callback=None,
) -> dict:
    """
    Phase 1: Identify candidate changes programmatically, validate against
    manifest, pre-extract pages for mini-agents.

    Returns:
    {
        "candidates": [dict, ...],
        "manifest": dict or None,
        "page_cache": {("old"|"new", page_num): "text", ...},
        "tokens_used": int,
    }
    """
    start = time.time()
    effective_key = api_key or ANTHROPIC_API_KEY
    tokens_used = 0

    def emit(stage, percent, message, **kwargs):
        if progress_callback:
            progress_callback(ProgressEvent(
                stage=stage,
                percent=percent,
                message=message,
                elapsed=int(time.time() - start),
                timestamp=datetime.utcnow().isoformat(),
                **kwargs,
            ))

    # ── Step 1: Programmatic analysis (no Claude calls) ─────────────
    emit("orchestrator", 2, "Scanning document structure...")

    old_structure = detect_sections(old_pdf_path)
    new_structure = detect_sections(new_pdf_path)
    print(f"[orchestrator {job_id}] Structure: old={old_structure['count']} sections, "
          f"new={new_structure['count']} sections")

    emit("orchestrator", 5, "Scanning for revision history...")
    old_manifest = detect_revision_history(old_pdf_path)
    new_manifest = detect_revision_history(new_pdf_path)

    # Use whichever PDF has the richer manifest
    manifest = new_manifest if new_manifest.get("detected") else old_manifest
    manifest_items = []
    if manifest.get("detected"):
        items = manifest.get("items", {})
        for ref in items.get("revised", []):
            manifest_items.append({"ref": ref, "action": "revised"})
        for ref in items.get("added", []):
            manifest_items.append({"ref": ref, "action": "added"})
        for ref in items.get("deleted", []):
            manifest_items.append({"ref": ref, "action": "deleted"})
        print(f"[orchestrator {job_id}] Manifest detected: {len(manifest_items)} items")
    else:
        print(f"[orchestrator {job_id}] No manifest detected")

    emit("orchestrator", 10, "Running section-by-section diff...")
    diff_result = diff_sections(old_pdf_path, new_pdf_path)
    diffs = diff_result.get("diffs", [])
    print(f"[orchestrator {job_id}] Diff complete: {len(diffs)} differences found")

    # ── Step 2: Build candidate list from diffs ─────────────────────
    emit("orchestrator", 13, f"Building candidates from {len(diffs)} diffs...")

    candidates = []
    for i, d in enumerate(diffs):
        section = d.get("old_section") or d.get("new_section") or f"unknown_{i}"
        diff_type = d.get("type", "MODIFIED")

        # Determine pages to read
        old_pages = _find_pages_for_section(section, old_structure)
        new_pages = _find_pages_for_section(section, new_structure)

        candidates.append({
            "id": f"C{i+1:03d}",
            "section": section,
            "title": f"{diff_type}: {section}",
            "category_hint": diff_type,
            "old_pages": old_pages,
            "new_pages": new_pages,
            "diff_preview": d.get("diff_preview", "")[:200],
            "manifest_item": None,
            "similarity": d.get("similarity"),
        })

    # ── Step 3: Cross-check manifest ────────────────────────────────
    if manifest_items:
        emit("orchestrator", 15, "Cross-checking manifest coverage...")
        covered_sections = {_normalize_section_ref(c["section"]) for c in candidates}

        for item in manifest_items:
            ref_norm = _normalize_section_ref(item["ref"])
            if ref_norm not in covered_sections:
                # Manifest item not covered by diff — create synthetic candidate
                section_ref = item["ref"]
                action = item["action"]

                old_pages = _find_pages_for_section(section_ref, old_structure)
                new_pages = _find_pages_for_section(section_ref, new_structure)

                category_hint = {
                    "revised": "MODIFIED",
                    "added": "NEW",
                    "deleted": "REMOVED",
                }.get(action, "MODIFIED")

                candidates.append({
                    "id": f"C{len(candidates)+1:03d}",
                    "section": section_ref,
                    "title": f"{category_hint} (manifest): {section_ref}",
                    "category_hint": category_hint,
                    "old_pages": old_pages,
                    "new_pages": new_pages,
                    "diff_preview": f"From manifest: {section_ref} — {action}",
                    "manifest_item": f"{section_ref} — {action}",
                })
                covered_sections.add(ref_norm)
                print(f"[orchestrator {job_id}] Added manifest candidate: {section_ref} ({action})")

    # ── Step 4: Optional Claude validation (complex manifests only) ──
    if manifest_items and len(manifest_items) > 5 and effective_key:
        emit("orchestrator", 17, "Validating candidates with AI...")
        try:
            validation_result = _validate_with_claude(
                effective_key, candidates, manifest, old_structure, new_structure
            )
            tokens_used += validation_result.get("tokens", 0)
            extra_candidates = validation_result.get("extra_candidates", [])
            for extra in extra_candidates:
                extra["id"] = f"C{len(candidates)+1:03d}"
                candidates.append(extra)
                print(f"[orchestrator {job_id}] AI added candidate: {extra['section']}")
        except Exception as e:
            print(f"[orchestrator {job_id}] Claude validation failed (non-fatal): {e}")

    print(f"[orchestrator {job_id}] Total candidates: {len(candidates)}")

    # ── Step 5: Pre-extract pages for mini-agents ───────────────────
    emit("orchestrator", 18, f"Pre-extracting pages for {len(candidates)} candidates...")

    page_cache = {}
    pages_to_extract = set()  # (pdf_id, page_num) tuples

    for cand in candidates:
        for p in cand.get("old_pages", []):
            pages_to_extract.add(("old", p))
        for p in cand.get("new_pages", []):
            pages_to_extract.add(("new", p))

    for pdf_id, page_num in pages_to_extract:
        pdf_path = old_pdf_path if pdf_id == "old" else new_pdf_path
        try:
            result = extract_page_text(pdf_path, page_num)
            if "error" not in result:
                page_cache[(pdf_id, page_num)] = result["text"]
        except Exception as e:
            print(f"[orchestrator {job_id}] Failed to extract {pdf_id} p{page_num}: {e}")

    elapsed = int(time.time() - start)
    emit("candidates_ready", 20,
         f"Found {len(candidates)} candidate changes in {elapsed}s",
         candidates_found=len(candidates))
    print(f"[orchestrator {job_id}] Done in {elapsed}s. "
          f"Candidates={len(candidates)}, Pages cached={len(page_cache)}, "
          f"Tokens={tokens_used}")

    return {
        "candidates": candidates,
        "manifest": manifest if manifest.get("detected") else None,
        "page_cache": page_cache,
        "tokens_used": tokens_used,
    }


def _find_pages_for_section(section_ref: str, structure: dict) -> list[int]:
    """Find page numbers where a section appears. Returns 1-3 page numbers."""
    ref_lower = section_ref.lower().strip()
    sections = structure.get("sections", [])

    # Exact match first
    for s in sections:
        if s["number"].lower().strip() == ref_lower:
            page = s["page"]
            # Return this page + next page for context
            return [page, page + 1]

    # Partial match (e.g., "2.3" matches "2.3.1")
    for s in sections:
        if s["number"].lower().strip().startswith(ref_lower):
            page = s["page"]
            return [page, page + 1]

    # If section_ref looks like "Table 3", try matching title
    for s in sections:
        if ref_lower in s["number"].lower() or ref_lower in s.get("title", "").lower():
            page = s["page"]
            return [page, page + 1]

    return []  # Couldn't find — mini-agent will search


def _normalize_section_ref(ref: str) -> str:
    """Normalize section reference for comparison."""
    ref = ref.lower().strip().rstrip(".:;")
    # Remove extra spaces
    ref = re.sub(r'\s+', ' ', ref)
    return ref


def _validate_with_claude(api_key, candidates, manifest, old_structure, new_structure) -> dict:
    """Use Claude for 1 turn to check if any manifest items are missing."""
    client = anthropic.Anthropic(api_key=api_key)

    candidate_sections = [c["section"] for c in candidates]
    manifest_text = manifest.get("raw_text", "")[:3000]

    user_msg = (
        f"I have identified {len(candidates)} candidate changes from a document diff.\n\n"
        f"Candidate sections: {json.dumps(candidate_sections)}\n\n"
        f"Document manifest (revision history):\n{manifest_text}\n\n"
        f"Are there any items in the manifest that are NOT covered by the candidates? "
        f"If so, return a JSON array of missing items, each with: "
        f'{{"section": "...", "title": "...", "category_hint": "MODIFIED|NEW|REMOVED"}}. '
        f"If all items are covered, return an empty array []."
    )

    response = client.messages.create(
        model="claude-haiku-3-5-20241022",  # Use Haiku for this simple validation
        max_tokens=4096,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0,
    )

    tokens = response.usage.input_tokens + response.usage.output_tokens
    text = response.content[0].text if response.content else "[]"

    # Extract JSON from response
    try:
        # Find JSON array in response
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            extra = json.loads(match.group())
            if isinstance(extra, list):
                return {"tokens": tokens, "extra_candidates": extra}
    except (json.JSONDecodeError, AttributeError):
        pass

    return {"tokens": tokens, "extra_candidates": []}
