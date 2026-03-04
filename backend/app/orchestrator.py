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
    get_page_count,
)
from .models import ProgressEvent

# Docling-powered extraction (layout-aware, OCR, structured tables)
try:
    from .docling_extract import parse_pdf as docling_parse_pdf, diff_documents as docling_diff, match_tables
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False


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

    old_page_count = get_page_count(old_pdf_path)
    new_page_count = get_page_count(new_pdf_path)

    # Use Docling for layout-aware extraction when available
    docling_result = None
    old_docling = None
    new_docling = None
    table_matches = []

    if HAS_DOCLING:
        try:
            emit("orchestrator", 3, "Running Docling layout analysis (OCR + tables)...")
            docling_result = docling_diff(old_pdf_path, new_pdf_path)
            old_docling = docling_result["old_parsed"]
            new_docling = docling_result["new_parsed"]
            table_matches = docling_result.get("table_matches", [])
            print(f"[orchestrator {job_id}] Docling: {docling_result['summary']}")
        except Exception as e:
            print(f"[orchestrator {job_id}] Docling failed (falling back to regex): {e}")
            docling_result = None

    # Always run regex-based detection too (Docling supplements, doesn't fully replace)
    old_structure = detect_sections(old_pdf_path)
    new_structure = detect_sections(new_pdf_path)

    # Merge Docling sections into structure if available
    if old_docling:
        _merge_docling_sections(old_structure, old_docling)
    if new_docling:
        _merge_docling_sections(new_structure, new_docling)

    print(f"[orchestrator {job_id}] Structure: old={old_structure['count']} sections ({old_page_count} pages), "
          f"new={new_structure['count']} sections ({new_page_count} pages)")

    # Emit page counts early so frontend can set up PDF viewer
    emit("orchestrator", 5, "Scanning for revision history...",
         old_pages_count=old_page_count, new_pages_count=new_page_count)
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
    emit("orchestrator", 10, f"Building candidates from {len(diffs)} diffs...")

    candidates = []
    skipped_high_sim = 0
    for i, d in enumerate(diffs):
        section = d.get("old_section") or d.get("new_section") or f"unknown_{i}"
        diff_type = d.get("type", "MODIFIED")

        # Skip near-identical sections (similarity > 0.95 = likely no real change)
        similarity = d.get("similarity")
        if similarity is not None and similarity > 0.95 and diff_type == "MODIFIED":
            skipped_high_sim += 1
            continue

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
            "diff_preview": d.get("diff_preview", "")[:300],
            "old_text_preview": d.get("old_text_preview", "")[:800],
            "new_text_preview": d.get("new_text_preview", "")[:800],
            "manifest_item": None,
            "similarity": similarity,
        })

    if skipped_high_sim:
        print(f"[orchestrator {job_id}] Skipped {skipped_high_sim} near-identical sections (>95% similar)")

    # ── Step 2a: Add table-level candidates from Docling ─────────────
    if table_matches:
        table_candidates_added = 0
        covered_sections = {_normalize_section_ref(c["section"]) for c in candidates}
        for tm in table_matches:
            old_t = tm.get("old")
            new_t = tm.get("new")
            diff_info = tm.get("diff")

            # Determine table label and type
            if old_t and new_t:
                # Matched table pair — check for changes
                if not diff_info or not diff_info.get("has_changes"):
                    continue  # No changes in this table pair

                old_label = old_t["label"]
                new_label = new_t["label"]
                section_ref = new_label  # Use new label as section ref

                # Check if renumbered (different labels, same content structure)
                is_renumbered = old_label.lower() != new_label.lower()

                norm = _normalize_section_ref(section_ref)
                if norm in covered_sections:
                    continue

                # Build rich diff preview from cell-level changes
                diff_preview_parts = [diff_info["summary"]]
                for rc in diff_info.get("row_changes", [])[:5]:
                    if rc["type"] == "modified":
                        for cell in rc["cells"][:3]:
                            diff_preview_parts.append(
                                f"  {rc['key']}.{cell['column']}: {cell['old']} → {cell['new']}"
                            )
                    elif rc["type"] == "added":
                        diff_preview_parts.append(f"  + row: {rc['key']}")
                    elif rc["type"] == "removed":
                        diff_preview_parts.append(f"  - row: {rc['key']}")

                cat_hint = "STRUCTURAL" if is_renumbered else "MODIFIED"
                title = (
                    f"Table renumbered: {old_label} → {new_label}" if is_renumbered
                    else f"Table modified: {new_label}"
                )

                candidates.append({
                    "id": f"C{len(candidates)+1:03d}",
                    "section": section_ref,
                    "title": title,
                    "category_hint": cat_hint,
                    "old_pages": [old_t["page"]] if old_t.get("page") else [],
                    "new_pages": [new_t["page"]] if new_t.get("page") else [],
                    "diff_preview": "\n".join(diff_preview_parts),
                    "old_text_preview": old_t.get("markdown", "")[:800],
                    "new_text_preview": new_t.get("markdown", "")[:800],
                    "manifest_item": None,
                    "similarity": tm.get("similarity", 0.5),
                    "table_diff": diff_info,  # Rich structured diff for mini-agents
                    "relocation_hint": (
                        f"Table renumbered: '{old_label}' → '{new_label}' "
                        f"(matched by content, sim={tm['similarity']:.0%})"
                    ) if is_renumbered else None,
                })
                covered_sections.add(norm)
                table_candidates_added += 1

            elif old_t and not new_t:
                # Table removed
                section_ref = old_t["label"]
                norm = _normalize_section_ref(section_ref)
                if norm not in covered_sections:
                    candidates.append({
                        "id": f"C{len(candidates)+1:03d}",
                        "section": section_ref,
                        "title": f"Table removed: {section_ref}",
                        "category_hint": "REMOVED",
                        "old_pages": [old_t["page"]] if old_t.get("page") else [],
                        "new_pages": [],
                        "diff_preview": f"Table '{section_ref}' not found in new document",
                        "old_text_preview": old_t.get("markdown", "")[:800],
                        "new_text_preview": "",
                        "manifest_item": None,
                        "similarity": 0.0,
                    })
                    covered_sections.add(norm)
                    table_candidates_added += 1

            elif new_t and not old_t:
                # Table added
                section_ref = new_t["label"]
                norm = _normalize_section_ref(section_ref)
                if norm not in covered_sections:
                    candidates.append({
                        "id": f"C{len(candidates)+1:03d}",
                        "section": section_ref,
                        "title": f"New table: {section_ref}",
                        "category_hint": "NEW",
                        "old_pages": [],
                        "new_pages": [new_t["page"]] if new_t.get("page") else [],
                        "diff_preview": f"New table '{section_ref}' added",
                        "old_text_preview": "",
                        "new_text_preview": new_t.get("markdown", "")[:800],
                        "manifest_item": None,
                        "similarity": 0.0,
                    })
                    covered_sections.add(norm)
                    table_candidates_added += 1

        if table_candidates_added:
            print(f"[orchestrator {job_id}] Added {table_candidates_added} table-level candidates from Docling")

        # Also enrich existing regex-based candidates with table diff data
        # Use a smarter match: candidate "Table X" gets the table match where
        # old_label or new_label matches "Table X" specifically
        enriched = 0
        used_matches = set()
        for cand in candidates:
            if cand.get("table_diff"):
                continue  # Already has Docling data
            cand_norm = _normalize_section_ref(cand["section"])
            best_tm = None
            best_tm_idx = None
            for ti, tm in enumerate(table_matches):
                if ti in used_matches:
                    continue
                old_t = tm.get("old")
                new_t = tm.get("new")
                diff_info = tm.get("diff")
                if not diff_info or not diff_info.get("has_changes"):
                    continue
                # Prefer exact label match on old side (since regex diff uses old section names)
                if old_t and _normalize_section_ref(old_t["label"]) == cand_norm:
                    best_tm = tm
                    best_tm_idx = ti
                    break
                elif new_t and _normalize_section_ref(new_t["label"]) == cand_norm:
                    best_tm = tm
                    best_tm_idx = ti
                    # Don't break — prefer old-side match

            if best_tm and best_tm_idx is not None:
                used_matches.add(best_tm_idx)
                old_t = best_tm.get("old")
                new_t = best_tm.get("new")
                cand["table_diff"] = best_tm["diff"]
                # If tables were renumbered, add relocation hint
                if old_t and new_t and old_t["label"].lower() != new_t["label"].lower():
                    if not cand.get("relocation_hint"):
                        cand["relocation_hint"] = (
                            f"Table renumbered: '{old_t['label']}' → '{new_t['label']}' "
                            f"(matched by content, sim={best_tm['similarity']:.0%})"
                        )
                        cand["category_hint"] = "STRUCTURAL"
                enriched += 1
        if enriched:
            print(f"[orchestrator {job_id}] Enriched {enriched} existing candidates with Docling table diffs")

    # ── Step 2b: Detect relocations (content at same number but different) ─
    # When a document is majorly restructured, "Table 2" old might have completely
    # different content than "Table 2" new because everything shifted. Detect this
    # by cross-matching low-similarity MODIFIED diffs against all other diffs.
    candidates = _detect_relocations(candidates, diffs, job_id)

    # ── Step 2b: Opus diff pass — AI reads pages to find missed changes ──
    if effective_key:
        emit("orchestrator", 14, "Running AI diff pass (Opus)...")
        try:
            opus_result = _opus_diff_pass(
                effective_key, old_pdf_path, new_pdf_path,
                old_page_count, new_page_count,
                old_structure, new_structure, candidates
            )
            tokens_used += opus_result.get("tokens", 0)
            opus_candidates = opus_result.get("candidates", [])
            if opus_candidates:
                # Dedup: only add Opus candidates for sections not already covered
                covered = {_normalize_section_ref(c["section"]) for c in candidates}
                added = 0
                for oc in opus_candidates:
                    norm = _normalize_section_ref(oc.get("section", ""))
                    # Check if already covered (exact or prefix match)
                    is_covered = False
                    for cs in covered:
                        if cs == norm or cs.startswith(norm + ".") or norm.startswith(cs + "."):
                            is_covered = True
                            break
                    if not is_covered:
                        oc["id"] = f"C{len(candidates)+1:03d}"
                        oc["category_hint"] = oc.get("category_hint", "MODIFIED")
                        oc["old_pages"] = _find_pages_for_section(oc["section"], old_structure)
                        oc["new_pages"] = _find_pages_for_section(oc["section"], new_structure)
                        oc["diff_preview"] = oc.get("diff_preview", f"AI-identified: {oc.get('title', '')}")
                        candidates.append(oc)
                        covered.add(norm)
                        added += 1
                print(f"[orchestrator {job_id}] Opus diff pass: {len(opus_candidates)} found, {added} new (rest already covered)")
        except Exception as e:
            print(f"[orchestrator {job_id}] Opus diff pass failed (non-fatal): {e}")

    # ── Step 3: Cross-check manifest ────────────────────────────────
    if manifest_items:
        emit("orchestrator", 15, "Cross-checking manifest coverage...")
        covered_sections = {_normalize_section_ref(c["section"]) for c in candidates}

        def _is_covered(ref_norm: str) -> bool:
            """Check if a manifest ref is already covered by an existing candidate.
            Handles partial matches: manifest '2' covers diff '2.1', and vice versa."""
            if ref_norm in covered_sections:
                return True
            for cs in covered_sections:
                # '2.1' starts with '2' or '2' starts with '2.1'
                if cs.startswith(ref_norm + ".") or ref_norm.startswith(cs + "."):
                    return True
                if cs == ref_norm:
                    return True
            return False

        for item in manifest_items:
            ref_norm = _normalize_section_ref(item["ref"])
            if not _is_covered(ref_norm):
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

    # Cap candidates to prevent OOM on Railway
    MAX_CANDIDATES = 100
    if len(candidates) > MAX_CANDIDATES:
        print(f"[orchestrator {job_id}] Capping candidates from {len(candidates)} to {MAX_CANDIDATES}")
        # Sort by similarity (lower = more different = more likely a real change)
        candidates.sort(key=lambda c: c.get("similarity") or 0.5)
        candidates = candidates[:MAX_CANDIDATES]

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

    # First, populate from Docling if available (layout-aware, OCR-capable)
    if old_docling and old_docling.get("pages"):
        for page_no, text in old_docling["pages"].items():
            page_cache[("old", page_no)] = text
    if new_docling and new_docling.get("pages"):
        for page_no, text in new_docling["pages"].items():
            page_cache[("new", page_no)] = text

    # Fill remaining pages from pdfplumber (fallback for pages Docling didn't cover)
    for pdf_id, page_num in pages_to_extract:
        if (pdf_id, page_num) in page_cache:
            continue  # Already have from Docling
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

    # Build compact structure summaries for mini-agents
    def _structure_summary(struct, docling_parsed=None):
        sections = struct.get("sections", [])
        lines = []
        for s in sections[:80]:  # cap to avoid bloating prompts
            title = s.get("title", "")
            lines.append(f"  {s['number']}: {title} (p{s['page']})" if title else f"  {s['number']} (p{s['page']})")
        # Add table listing from Docling if available
        if docling_parsed and docling_parsed.get("tables"):
            lines.append("\n  Tables:")
            for t in docling_parsed["tables"]:
                cols = ", ".join(str(c) for c in t.get("columns", []))
                lines.append(f"    {t['label']} (p{t['page']}): columns=[{cols}], {len(t.get('rows', []))} rows")
        return "\n".join(lines) if lines else "(no sections detected)"

    return {
        "candidates": candidates,
        "manifest": manifest if manifest.get("detected") else None,
        "page_cache": page_cache,
        "tokens_used": tokens_used,
        "old_structure_summary": _structure_summary(old_structure, old_docling),
        "new_structure_summary": _structure_summary(new_structure, new_docling),
    }


def _merge_docling_sections(structure: dict, docling_parsed: dict):
    """Merge Docling-detected sections into the regex-based structure dict.
    Only adds sections not already present (by normalized number)."""
    existing = set()
    for s in structure.get("sections", []):
        existing.add(s["number"].lower().strip())
        # Also add with title for "Table X: Title" style entries
        full = f"{s['number']}: {s.get('title', '')}".lower().strip().rstrip(":")
        existing.add(full)

    for ds in docling_parsed.get("sections", []):
        num = ds["number"].lower().strip()
        if num not in existing:
            structure["sections"].append({
                "number": ds["number"],
                "title": ds["title"],
                "page": ds["page"],
            })
            existing.add(num)

    # Also add table entries as sections for structure matching
    for dt in docling_parsed.get("tables", []):
        label = dt["label"]
        num = label.lower().strip()
        if num not in existing:
            structure["sections"].append({
                "number": label,
                "title": "",
                "page": dt["page"],
            })
            existing.add(num)

    structure["count"] = len(structure["sections"])
    # Sort by page then number
    structure["sections"].sort(key=lambda s: (s["page"], s["number"]))


def _detect_relocations(candidates: list[dict], diffs: list[dict], job_id: str) -> list[dict]:
    """
    Detect when low-similarity MODIFIED candidates are actually relocations.

    When a document is massively restructured (e.g., 88→44 pages), section numbers
    shift. "Table 2" in old might contain "Equipment specs" while "Table 2" in new
    contains "Test matrix" — because old Table 2's content moved to Table 3 and
    old Table 1's content moved into Table 2's slot.

    This function cross-matches content previews to detect these patterns and
    annotates candidates with relocation hints so mini-agents can classify correctly.
    """
    from difflib import SequenceMatcher

    # Build lookup: section → diff item (for content matching)
    diff_by_section = {}
    for d in diffs:
        sec = d.get("old_section") or d.get("new_section", "")
        diff_by_section[sec.lower().strip()] = d

    # Collect all old and new text previews for cross-matching
    old_contents = {}  # section → old_text_preview
    new_contents = {}  # section → new_text_preview
    for c in candidates:
        sec = c.get("section", "").lower().strip()
        old_preview = c.get("old_text_preview", "")
        new_preview = c.get("new_text_preview", "")
        if old_preview:
            old_contents[sec] = old_preview
        if new_preview:
            new_contents[sec] = new_preview

    if not old_contents or not new_contents:
        return candidates

    relocation_count = 0
    for cand in candidates:
        # Only check MODIFIED candidates with low similarity (very different content)
        if cand.get("category_hint") != "MODIFIED":
            continue
        sim = cand.get("similarity")
        if sim is not None and sim > 0.4:
            continue  # Similarity above 0.4 = probably a real modification, not relocation

        cand_section = cand.get("section", "").lower().strip()
        old_text = cand.get("old_text_preview", "")
        new_text = cand.get("new_text_preview", "")

        if not old_text or not new_text:
            continue

        # Check: does the OLD content of this section appear in a DIFFERENT section
        # in the NEW document? (i.e., was the content relocated?)
        old_relocated_to = None
        best_old_match = 0.0
        for other_sec, other_new_text in new_contents.items():
            if other_sec == cand_section:
                continue
            ratio = SequenceMatcher(None,
                                    old_text[:600].lower(),
                                    other_new_text[:600].lower()).ratio()
            if ratio > best_old_match and ratio > 0.5:
                best_old_match = ratio
                old_relocated_to = other_sec

        # Check: does the NEW content of this section come from a DIFFERENT section
        # in the OLD document? (i.e., was content moved into this slot?)
        new_came_from = None
        best_new_match = 0.0
        for other_sec, other_old_text in old_contents.items():
            if other_sec == cand_section:
                continue
            ratio = SequenceMatcher(None,
                                    new_text[:600].lower(),
                                    other_old_text[:600].lower()).ratio()
            if ratio > best_new_match and ratio > 0.5:
                best_new_match = ratio
                new_came_from = other_sec

        # If we found relocation evidence, annotate the candidate
        if old_relocated_to or new_came_from:
            hints = []
            if old_relocated_to:
                hints.append(f"old content (sim={best_old_match:.0%}) now at '{old_relocated_to}'")
            if new_came_from:
                hints.append(f"new content (sim={best_new_match:.0%}) came from '{new_came_from}'")

            cand["relocation_hint"] = "; ".join(hints)
            cand["category_hint"] = "STRUCTURAL"
            cand["title"] = f"RELOCATED: {cand['section']} — {'; '.join(hints)}"
            relocation_count += 1
            print(f"[orchestrator {job_id}] Relocation detected: {cand['section']} — {'; '.join(hints)}")

    if relocation_count:
        print(f"[orchestrator {job_id}] Detected {relocation_count} relocations from content matching")

    return candidates


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

    # Reverse partial match (e.g., ref "2.3.1" matches structure "2.3")
    for s in sections:
        s_num = s["number"].lower().strip()
        if ref_lower.startswith(s_num + ".") or ref_lower.startswith(s_num + " "):
            page = s["page"]
            return [page, page + 1]

    # If section_ref looks like "Table 3", try matching title
    for s in sections:
        if ref_lower in s["number"].lower() or ref_lower in s.get("title", "").lower():
            page = s["page"]
            return [page, page + 1]

    # Try extracting just the numeric part and matching
    num_match = re.match(r'^(?:section|clause|table|appendix|annex|figure|fig\.?)\s*(\d[\d.]*)', ref_lower)
    if num_match:
        just_num = num_match.group(1).rstrip(".")
        for s in sections:
            s_num = s["number"].lower().strip()
            if s_num == just_num or s_num.startswith(just_num + "."):
                page = s["page"]
                return [page, page + 1]

    # Fuzzy: try matching any significant word from the ref against section titles
    ref_words = set(re.findall(r'[a-z]{3,}', ref_lower)) - {"the", "and", "for", "section", "table"}
    if ref_words:
        best_score = 0
        best_page = None
        for s in sections:
            title_lower = (s.get("title", "") + " " + s["number"]).lower()
            title_words = set(re.findall(r'[a-z]{3,}', title_lower))
            overlap = len(ref_words & title_words)
            if overlap > best_score:
                best_score = overlap
                best_page = s["page"]
        if best_score >= 2 or (best_score >= 1 and len(ref_words) <= 2):
            return [best_page, best_page + 1]

    return []  # Couldn't find — mini-agent will get broader context


def _normalize_section_ref(ref: str) -> str:
    """
    Normalize section reference for comparison.
    Extracts the leading numeric/dotted pattern (e.g., "2.3.1") to match
    regardless of trailing title text, punctuation, or formatting differences.
    """
    ref = ref.lower().strip().rstrip(".:;")
    ref = re.sub(r'\s+', ' ', ref)

    # Extract leading section number like "2.3", "A.1", "Table 3", etc.
    num_match = re.match(r'^((?:table|appendix|annex|figure|fig)\s*)?(\d[\d.]*[a-z]?)', ref)
    if num_match:
        prefix = (num_match.group(1) or "").strip()
        number = num_match.group(2).rstrip(".")
        return f"{prefix} {number}".strip() if prefix else number

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
        model="claude-opus-4-6",  # Opus for best completeness on this critical first pass
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


def _opus_diff_pass(
    api_key, old_pdf_path, new_pdf_path,
    old_page_count, new_page_count,
    old_structure, new_structure,
    existing_candidates
) -> dict:
    """
    Send full document text from both PDFs to Opus and ask it to identify
    all changes, including ones the programmatic diff may have missed.

    Sends all pages by default (Opus has 200K context). Only truncates
    individual pages if the total would be extremely large (>500 pages).

    Returns {"tokens": int, "candidates": [dict, ...]}.
    """
    from .pdf_utils import extract_page_text

    client = anthropic.Anthropic(api_key=api_key)

    # For very large docs (>500 pages), truncate per-page text to stay in context
    total_pages = old_page_count + new_page_count
    per_page_limit = 0  # 0 = no limit
    if total_pages > 500:
        per_page_limit = 1500  # ~750K chars total, fits in 200K tokens
    elif total_pages > 200:
        per_page_limit = 3000

    # Extract ALL pages from both docs
    old_text_blocks = []
    for p in range(1, old_page_count + 1):
        result = extract_page_text(old_pdf_path, p)
        text = result.get("text", "")
        if text:
            if per_page_limit:
                text = text[:per_page_limit]
            old_text_blocks.append(f"--- OLD Page {p} ---\n{text}")

    new_text_blocks = []
    for p in range(1, new_page_count + 1):
        result = extract_page_text(new_pdf_path, p)
        text = result.get("text", "")
        if text:
            if per_page_limit:
                text = text[:per_page_limit]
            new_text_blocks.append(f"--- NEW Page {p} ---\n{text}")

    old_text = "\n\n".join(old_text_blocks)
    new_text = "\n\n".join(new_text_blocks)

    print(f"[opus-diff] Sending {old_page_count}+{new_page_count} pages "
          f"({len(old_text)//1000}K + {len(new_text)//1000}K chars)")

    # List existing candidates so Opus can focus on what's missing
    existing_sections = [c["section"] for c in existing_candidates]

    user_msg = (
        f"I am comparing two versions of a PDF document.\n\n"
        f"A programmatic diff has already identified these candidate change sections:\n"
        f"{json.dumps(existing_sections)}\n\n"
        f"Below is the COMPLETE extracted text from both document versions. "
        f"Please carefully read and compare them page by page and identify ANY "
        f"changes that the programmatic diff may have missed. Look for:\n"
        f"- Wording changes (even single words or numbers)\n"
        f"- Added or removed paragraphs, sentences, or bullet points\n"
        f"- Changes in tables (values, rows, columns)\n"
        f"- New or removed sections\n"
        f"- Changes in references, dates, version numbers\n"
        f"- Regulatory or compliance language changes\n"
        f"- Any formatting or structural differences\n\n"
        f"Return a JSON array of additional candidates NOT already in the list above. "
        f"Each item should have:\n"
        f'{{"section": "section ref", "title": "brief description", '
        f'"category_hint": "NEW|MODIFIED|REMOVED|FORMATTING", '
        f'"diff_preview": "brief description of what changed"}}\n\n'
        f"If no additional changes are found, return [].\n"
        f"Be thorough — it is better to flag a potential change than to miss one.\n\n"
        f"=== OLD DOCUMENT ({old_page_count} pages) ===\n{old_text}\n\n"
        f"=== NEW DOCUMENT ({new_page_count} pages) ===\n{new_text}"
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": user_msg}],
        temperature=0,
    )

    tokens = response.usage.input_tokens + response.usage.output_tokens
    text = response.content[0].text if response.content else "[]"
    print(f"[opus-diff] Response: {tokens} tokens, {len(text)} chars")

    # Extract JSON array from response
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            candidates = json.loads(match.group())
            if isinstance(candidates, list):
                return {"tokens": tokens, "candidates": candidates}
    except (json.JSONDecodeError, AttributeError):
        pass

    return {"tokens": tokens, "candidates": []}
