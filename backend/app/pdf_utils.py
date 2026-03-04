"""
PDF processing utilities: text extraction, search, section parsing,
revision history detection, diff engine, and annotation.
"""
import pdfplumber
import fitz  # PyMuPDF
import re
import os
import difflib
from typing import Optional


# ── TEXT EXTRACTION ──────────────────────────────────────────────────

def extract_full_text(pdf_path: str) -> dict:
    """Extract all text from a PDF with per-page structure."""
    pages = []
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append({"page": i + 1, "text": text, "char_count": len(text)})
            full_text += text + "\n"
    return {
        "total_pages": len(pages),
        "total_chars": len(full_text),
        "pages": pages,
        "full_text": full_text,
    }


def extract_page_text(pdf_path: str, page_num: int) -> dict:
    """Extract text from a single page."""
    with pdfplumber.open(pdf_path) as pdf:
        if page_num < 1 or page_num > len(pdf.pages):
            return {"error": f"Page {page_num} out of range (1-{len(pdf.pages)})"}
        page = pdf.pages[page_num - 1]
        text = page.extract_text() or ""
        return {"page": page_num, "text": text, "char_count": len(text)}


# ── SECTION PARSING ─────────────────────────────────────────────────

def detect_sections(pdf_path: str) -> dict:
    """Parse document structure — find section headings."""
    section_pattern = re.compile(
        r'^(\d+(?:\.\d+)*)\s+([A-Z][\w\s\-/,()]+)',
        re.MULTILINE
    )
    appendix_pattern = re.compile(
        r'^(Appendix\s+[\w\d\.]+|Table\s+[\w\d\.]+|Figure\s+[\d]+)\s*[:\-—]?\s*(.*)',
        re.MULTILINE | re.IGNORECASE
    )

    sections = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for m in section_pattern.finditer(text):
                sections.append({
                    "number": m.group(1).strip(),
                    "title": m.group(2).strip()[:80],
                    "page": i + 1,
                })
            for m in appendix_pattern.finditer(text):
                sections.append({
                    "number": m.group(1).strip(),
                    "title": m.group(2).strip()[:80],
                    "page": i + 1,
                })

    # Deduplicate
    seen = set()
    unique = []
    for s in sections:
        key = s["number"]
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return {"sections": unique, "count": len(unique)}


# ── REVISION HISTORY DETECTION ──────────────────────────────────────

def detect_revision_history(pdf_path: str, max_pages_to_scan: int = 8) -> dict:
    """Scan document for revision history / change manifest."""
    # Strong keywords (score 2 each — any one of these is sufficient)
    strong_keywords = [
        "revision history", "change summary", "change record",
        "change log", "revision record", "document history", "change manifest",
    ]
    # Weak keywords (score 1 each — need 2+ to trigger)
    weak_keywords = [
        "what's new", "sections revised", "sections added", "sections deleted",
        "brief summary", "affected sections", "date of change",
    ]
    manifest_section_pattern = re.compile(
        r'(?:Section|Clause|Para(?:graph)?|Table|Figure|Appendix)\s+'
        r'[\d\.A-Za-z]+\s*[\-—:]\s*(?:Revised|Added|Deleted|Modified|New|Removed|Updated|Changed)',
        re.IGNORECASE
    )
    list_pattern = re.compile(
        r'(?:Revised|Added|Deleted|Modified|New|Removed)[\s:]+(.+)',
        re.IGNORECASE
    )

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        # Scan first 3 pages + last N pages (manifest often at start or end)
        pages_to_scan = list(range(min(3, total_pages)))
        pages_to_scan += list(range(max(0, total_pages - max_pages_to_scan), total_pages))
        pages_to_scan = sorted(set(pages_to_scan))

        found_pages = []
        raw_text = ""

        for page_idx in pages_to_scan:
            page = pdf.pages[page_idx]
            text = (page.extract_text() or "").lower()

            score = 0
            for kw in strong_keywords:
                if kw in text:
                    score += 2
            for kw in weak_keywords:
                if kw in text:
                    score += 1

            if manifest_section_pattern.search(page.extract_text() or ""):
                score += 3

            if score >= 2:
                found_pages.append(page_idx + 1)
                raw_text += (page.extract_text() or "") + "\n"

        if not found_pages:
            return {"detected": False, "pages": [], "items": {}}

        # Parse manifest items
        revised, added, deleted = [], [], []
        current_category = None
        for line in raw_text.split("\n"):
            line_lower = line.strip().lower()
            if "revised" in line_lower or "modified" in line_lower or "updated" in line_lower:
                current_category = "revised"
            elif "added" in line_lower or "new" in line_lower:
                current_category = "added"
            elif "deleted" in line_lower or "removed" in line_lower:
                current_category = "deleted"

            # Look for section references
            refs = re.findall(r'(\d+(?:\.\d+)+|Table\s+[\w\d\.]+|Figure\s+\d+|Appendix\s+[\w\d\.]+)', line)
            for ref in refs:
                ref = ref.strip()
                if current_category == "revised":
                    revised.append(ref)
                elif current_category == "added":
                    added.append(ref)
                elif current_category == "deleted":
                    deleted.append(ref)

        return {
            "detected": True,
            "pages": found_pages,
            "raw_text": raw_text[:3000],
            "items": {
                "revised": list(set(revised)),
                "added": list(set(added)),
                "deleted": list(set(deleted)),
            },
        }


# ── TEXT SEARCH ─────────────────────────────────────────────────────

def search_document(pdf_path: str, query: str, context_chars: int = 120) -> dict:
    """Search for text in a PDF with word-boundary matching."""
    with pdfplumber.open(pdf_path) as pdf:
        results = []
        full_text = ""
        page_boundaries = []

        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            start = len(full_text)
            full_text += text + "\n"
            page_boundaries.append((i + 1, start, start + len(text)))

        # Word-boundary search
        try:
            pattern = re.compile(re.escape(query), re.IGNORECASE)
            for match in pattern.finditer(full_text):
                pos = match.start()
                # Find page
                page_num = 1
                for pn, start, end in page_boundaries:
                    if start <= pos <= end:
                        page_num = pn
                        break
                ctx_start = max(0, pos - context_chars)
                ctx_end = min(len(full_text), match.end() + context_chars)
                results.append({
                    "page": page_num,
                    "position": pos,
                    "context": full_text[ctx_start:ctx_end].replace("\n", " "),
                    "match_text": match.group(),
                })
        except re.error:
            pass

    return {
        "query": query,
        "total_matches": len(results),
        "results": results[:20],  # Limit to 20 matches
    }


# ── DIFF ENGINE ─────────────────────────────────────────────────────

def _extract_section_texts(pdf_path: str) -> dict:
    """Extract text grouped by section number."""
    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    # Split by section headers
    section_split = re.compile(r'^(\d+(?:\.\d+)*)\s+', re.MULTILINE)
    sections = {}
    current_section = "_preamble"
    current_text = []

    for line in full_text.split("\n"):
        m = section_split.match(line)
        if m:
            if current_text:
                sections[current_section] = "\n".join(current_text)
            current_section = m.group(1)
            current_text = [line]
        else:
            current_text.append(line)
    if current_text:
        sections[current_section] = "\n".join(current_text)

    return sections


def diff_sections(old_pdf_path: str, new_pdf_path: str, section_map: Optional[dict] = None) -> dict:
    """Run section-by-section diff between two PDFs."""
    old_sections = _extract_section_texts(old_pdf_path)
    new_sections = _extract_section_texts(new_pdf_path)

    if section_map is None:
        section_map = {}

    diffs = []
    processed_new = set()

    # Compare old sections against new
    for old_num, old_text in old_sections.items():
        new_num = section_map.get(old_num, old_num)
        if new_num in new_sections:
            new_text = new_sections[new_num]
            processed_new.add(new_num)

            ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
            if ratio < 0.98:  # Threshold for meaningful change
                # Generate unified diff
                diff_lines = list(difflib.unified_diff(
                    old_text.splitlines(), new_text.splitlines(),
                    fromfile=f"Old §{old_num}", tofile=f"New §{new_num}",
                    lineterm="",
                ))
                added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
                removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

                diffs.append({
                    "old_section": old_num,
                    "new_section": new_num,
                    "type": "MODIFIED",
                    "similarity": round(ratio, 3),
                    "lines_added": added,
                    "lines_removed": removed,
                    "diff_preview": "\n".join(diff_lines[:30]),
                    "old_text_preview": old_text[:500],
                    "new_text_preview": new_text[:500],
                })
        else:
            diffs.append({
                "old_section": old_num,
                "new_section": None,
                "type": "REMOVED",
                "old_text_preview": old_text[:500],
            })

    # Find new sections
    for new_num, new_text in new_sections.items():
        if new_num not in processed_new and new_num not in old_sections:
            diffs.append({
                "old_section": None,
                "new_section": new_num,
                "type": "NEW",
                "new_text_preview": new_text[:500],
            })

    # Sort by section number
    def sort_key(d):
        s = d.get("old_section") or d.get("new_section") or ""
        parts = re.findall(r'\d+', s)
        return [int(p) for p in parts] if parts else [999]

    diffs.sort(key=sort_key)

    return {
        "total_diffs": len(diffs),
        "old_sections": len(old_sections),
        "new_sections": len(new_sections),
        "diffs": diffs,
    }


# ── PDF ANNOTATION ──────────────────────────────────────────────────

def annotate_pdf(pdf_path: str, output_path: str, annotations: list) -> dict:
    """
    Create annotated PDF with two-layer highlighting.
    annotations: list of {"search_text": str, "page": int (optional)}
    """
    if os.path.exists(output_path):
        os.remove(output_path)

    doc = fitz.open(pdf_path)
    highlight_count = 0
    page_map = {}

    for ann in annotations:
        search_text = ann.get("search_text")
        change_id = ann.get("change_id", 0)
        if not search_text:
            continue

        # Search across pages
        found = False
        for page_num in range(len(doc)):
            page = doc[page_num]
            try:
                rects = page.search_for(search_text, quads=False)
            except Exception:
                continue
            if rects:
                try:
                    # Layer 1: Paragraph background (light yellow rect)
                    para_rect = _expand_to_paragraph(page, rects)
                    if para_rect:
                        rect_annot = page.add_rect_annot(para_rect)
                        rect_annot.set_colors(stroke=(0.9, 0.85, 0.5), fill=(1.0, 1.0, 0.8))
                        rect_annot.set_opacity(0.25)
                        rect_annot.set_border(width=0.5)
                        rect_annot.update()

                    # Layer 2: Specific text highlight (orange)
                    # Filter out invalid rects before highlighting
                    valid_rects = [r for r in rects if not r.is_infinite and not r.is_empty and r.width > 0 and r.height > 0]
                    if valid_rects:
                        highlight = page.add_highlight_annot(valid_rects)
                        highlight.set_colors(stroke=(1.0, 0.6, 0.0))
                        highlight.set_opacity(0.45)
                        highlight.update()
                except (ValueError, RuntimeError) as e:
                    # Skip this annotation if rect is invalid — don't crash the whole job
                    print(f"[annotate] Skipping change #{change_id} on page {page_num+1}: {e}")

                highlight_count += 1
                page_map[change_id] = page_num + 1
                found = True
                break

        # Fallback: try shorter snippet
        if not found and len(search_text) > 25:
            shorter = search_text[:30]
            for page_num in range(len(doc)):
                page = doc[page_num]
                try:
                    rects = page.search_for(shorter, quads=False)
                except Exception:
                    continue
                if rects:
                    try:
                        valid_rects = [r for r in rects if not r.is_infinite and not r.is_empty and r.width > 0 and r.height > 0]
                        if valid_rects:
                            highlight = page.add_highlight_annot(valid_rects)
                            highlight.set_colors(stroke=(1.0, 0.6, 0.0))
                            highlight.set_opacity(0.35)
                            highlight.update()
                    except (ValueError, RuntimeError) as e:
                        print(f"[annotate] Skipping fallback change #{change_id} on page {page_num+1}: {e}")
                    highlight_count += 1
                    page_map[change_id] = page_num + 1
                    break

    doc.save(output_path)
    doc.close()

    return {"highlights": highlight_count, "page_map": page_map, "output": output_path}


def _expand_to_paragraph(page, rects):
    """Expand highlight rects to cover the full surrounding paragraph."""
    if not rects:
        return None

    # Filter out any invalid rects
    valid_rects = []
    for r in rects:
        try:
            if r.is_infinite or r.is_empty:
                continue
            if r.width > 0 and r.height > 0:
                valid_rects.append(r)
        except Exception:
            continue

    if not valid_rects:
        return None

    x0 = min(r.x0 for r in valid_rects)
    y0 = min(r.y0 for r in valid_rects)
    x1 = max(r.x1 for r in valid_rects)
    y1 = max(r.y1 for r in valid_rects)

    # Sanity check the bounding box
    if x0 >= x1 or y0 >= y1:
        return None

    blocks = page.get_text("blocks")
    para_rect = fitz.Rect(x0, y0, x1, y1)

    for block in blocks:
        bx0, by0, bx1, by1 = block[:4]
        block_type = block[6] if len(block) > 6 else 0
        if block_type != 0:
            continue
        try:
            block_rect = fitz.Rect(bx0, by0, bx1, by1)
            if block_rect.is_infinite or block_rect.is_empty:
                continue
            if block_rect.width <= 0 or block_rect.height <= 0:
                continue
            if block_rect.intersects(para_rect):
                para_rect = para_rect | block_rect
        except Exception:
            continue

    # Clamp to page bounds with padding
    para_rect.x0 = max(0, para_rect.x0 - 3)
    para_rect.y0 = max(0, para_rect.y0 - 2)
    para_rect.x1 = min(page.rect.width, para_rect.x1 + 3)
    para_rect.y1 = min(page.rect.height, para_rect.y1 + 2)

    # Final validation — must be a valid, finite, non-empty rect
    try:
        if para_rect.is_infinite or para_rect.is_empty:
            return None
        if para_rect.width <= 0 or para_rect.height <= 0:
            return None
    except Exception:
        return None

    return para_rect
