"""
Docling-powered PDF extraction: layout-aware structure detection, table extraction
as DataFrames, OCR for scanned pages, and structured diffing.

Replaces the regex-based detect_sections() and pdfplumber-based text extraction
with Docling + spaCy-layout for much richer document understanding.
"""
import os
import re
import time
import json
import hashlib
from typing import Optional
from difflib import SequenceMatcher

import spacy
from spacy_layout import spaCyLayout

# Module-level singleton — initialized lazily
_nlp = None
_layout = None
_doc_cache: dict[str, object] = {}  # path_hash → spacy Doc


def _get_layout():
    """Lazy-initialize the spaCy + Docling pipeline (heavy, ~2-3s first call)."""
    global _nlp, _layout
    if _layout is None:
        _nlp = spacy.blank("en")
        _layout = spaCyLayout(_nlp)
    return _layout


def _cache_key(pdf_path: str) -> str:
    """Generate cache key from file path + mtime."""
    mtime = os.path.getmtime(pdf_path)
    return hashlib.md5(f"{pdf_path}:{mtime}".encode()).hexdigest()


def parse_pdf(pdf_path: str, use_cache: bool = True) -> dict:
    """
    Parse a PDF using Docling + spaCy-layout.

    Returns a rich structure:
    {
        "sections": [
            {
                "number": "1.2",
                "title": "Scope",
                "type": "section_header",
                "page": 1,
                "text": "full text under this heading...",
            }, ...
        ],
        "tables": [
            {
                "label": "Table 1: Test Parameters",
                "page": 1,
                "heading": "2 Scope",  # parent section
                "columns": ["Parameter", "Min", "Max", "Unit"],
                "rows": [["Temperature", "-40", "125", "C"], ...],
                "markdown": "| Parameter | Min | Max | Unit |\n...",
                "dataframe": <pandas.DataFrame>,
            }, ...
        ],
        "pages": {
            1: "full text of page 1 with layout preserved...",
            2: "full text of page 2...",
        },
        "markdown": "full markdown representation",
        "count": <number of sections>,
        "page_count": <total pages>,
        "layout_spans": [<raw span data for advanced use>],
    }
    """
    key = _cache_key(pdf_path)
    layout = _get_layout()

    # Check cache
    if use_cache and key in _doc_cache:
        doc = _doc_cache[key]
    else:
        doc = layout(pdf_path)
        if use_cache:
            _doc_cache[key] = doc

    # Extract sections (headings + their content)
    sections = []
    current_heading = None
    current_text_parts = []
    current_page = 1

    for span in doc.spans.get("layout", []):
        label = span.label_
        page_no = span._.layout.page_no if span._.layout else 1

        if label in ("section_header", "title", "page_header"):
            # Save previous section
            if current_heading is not None:
                sections.append({
                    "number": _extract_section_number(current_heading),
                    "title": _extract_section_title(current_heading),
                    "type": label,
                    "page": current_page,
                    "text": "\n".join(current_text_parts).strip(),
                })
            current_heading = span.text.strip()
            current_text_parts = []
            current_page = page_no
        elif label == "caption":
            # Captions for tables/figures — treat as sub-sections
            if current_heading is not None and current_text_parts:
                sections.append({
                    "number": _extract_section_number(current_heading),
                    "title": _extract_section_title(current_heading),
                    "type": "section_header",
                    "page": current_page,
                    "text": "\n".join(current_text_parts).strip(),
                })
            current_heading = span.text.strip()
            current_text_parts = []
            current_page = page_no
        elif label == "text":
            current_text_parts.append(span.text.strip())

    # Don't forget the last section
    if current_heading is not None:
        sections.append({
            "number": _extract_section_number(current_heading),
            "title": _extract_section_title(current_heading),
            "type": "section_header",
            "page": current_page,
            "text": "\n".join(current_text_parts).strip(),
        })

    # Extract tables as structured data
    # First, build a list of all caption spans with their positions
    caption_spans = []
    for span in doc.spans.get("layout", []):
        if span.label_ == "caption" and span._.layout:
            caption_spans.append({
                "text": span.text.strip(),
                "page": span._.layout.page_no,
                "y": span._.layout.y,
            })

    tables = []
    used_captions = set()
    for i, table_span in enumerate(doc._.tables):
        df = table_span._.data
        if df is None:
            continue

        # Find the caption/label for this table by proximity
        table_label = f"Table {i+1}"
        heading_text = ""
        if table_span._.heading:
            heading_text = table_span._.heading.text.strip()

        table_page = table_span._.layout.page_no if table_span._.layout else 1
        table_y = table_span._.layout.y if table_span._.layout else 0

        # Find closest caption on the same page that's above the table
        best_caption = None
        best_dist = float("inf")
        for ci, cap in enumerate(caption_spans):
            if ci in used_captions:
                continue
            if cap["page"] == table_page and "table" in cap["text"].lower():
                dist = abs(cap["y"] - table_y)
                if dist < best_dist:
                    best_dist = dist
                    best_caption = (ci, cap["text"])

        if best_caption:
            used_captions.add(best_caption[0])
            table_label = best_caption[1]

        tables.append({
            "label": table_label,
            "page": table_page,
            "heading": heading_text,
            "columns": df.columns.tolist(),
            "rows": df.values.tolist(),
            "markdown": df.to_markdown(index=False) if hasattr(df, 'to_markdown') else str(df),
            "dataframe": df,
        })

    # Extract per-page text
    pages = {}
    if doc._.pages:
        for page_layout, page_spans in doc._.pages:
            page_no = page_layout.page_no
            page_text_parts = []
            for span in page_spans:
                if span._.data is not None:
                    # Table — include as markdown
                    page_text_parts.append(f"[TABLE]\n{span._.data.to_markdown(index=False) if hasattr(span._.data, 'to_markdown') else str(span._.data)}\n[/TABLE]")
                else:
                    page_text_parts.append(span.text.strip())
            pages[page_no] = "\n\n".join(page_text_parts)

    # Full markdown
    markdown = doc._.markdown if hasattr(doc._, 'markdown') else ""

    return {
        "sections": sections,
        "tables": tables,
        "pages": pages,
        "markdown": markdown,
        "count": len(sections),
        "page_count": len(pages) or 1,
        "layout_spans": [
            {
                "label": span.label_,
                "text": span.text[:200],
                "page": span._.layout.page_no if span._.layout else 1,
                "heading": span._.heading.text[:100] if span._.heading else None,
            }
            for span in doc.spans.get("layout", [])
        ],
    }


def diff_tables(old_table: dict, new_table: dict) -> dict:
    """
    Cell-level diff between two structured tables.

    Returns:
    {
        "has_changes": bool,
        "summary": str,
        "column_changes": {"added": [...], "removed": [...], "common": [...]},
        "row_changes": [
            {"type": "modified", "row": 0, "cells": [
                {"column": "Max", "old": "125", "new": "150"},
            ]},
            {"type": "added", "row": 2, "data": [...]},
            {"type": "removed", "row": 1, "data": [...]},
        ],
    }
    """
    old_cols = old_table.get("columns", [])
    new_cols = new_table.get("columns", [])
    old_rows = old_table.get("rows", [])
    new_rows = new_table.get("rows", [])

    # Column changes
    old_col_set = set(str(c) for c in old_cols)
    new_col_set = set(str(c) for c in new_cols)
    added_cols = list(new_col_set - old_col_set)
    removed_cols = list(old_col_set - new_col_set)
    common_cols = list(old_col_set & new_col_set)

    # Build column index maps
    old_col_idx = {str(c): i for i, c in enumerate(old_cols)}
    new_col_idx = {str(c): i for i, c in enumerate(new_cols)}

    # Row-by-row comparison using first column as key (if common)
    row_changes = []
    if common_cols and old_rows and new_rows:
        # Use first column as row identifier
        key_col = str(old_cols[0]) if str(old_cols[0]) in new_col_set else common_cols[0]
        old_key_idx = old_col_idx.get(key_col, 0)
        new_key_idx = new_col_idx.get(key_col, 0)

        old_by_key = {}
        for i, row in enumerate(old_rows):
            k = str(row[old_key_idx]) if old_key_idx < len(row) else f"row_{i}"
            old_by_key[k] = (i, row)

        new_by_key = {}
        for i, row in enumerate(new_rows):
            k = str(row[new_key_idx]) if new_key_idx < len(row) else f"row_{i}"
            new_by_key[k] = (i, row)

        # Find modified, added, removed rows
        for key in old_by_key:
            if key in new_by_key:
                old_idx, old_row = old_by_key[key]
                new_idx, new_row = new_by_key[key]
                cell_changes = []
                for col in common_cols:
                    oi = old_col_idx.get(col, -1)
                    ni = new_col_idx.get(col, -1)
                    old_val = str(old_row[oi]) if 0 <= oi < len(old_row) else ""
                    new_val = str(new_row[ni]) if 0 <= ni < len(new_row) else ""
                    if old_val != new_val:
                        cell_changes.append({
                            "column": col,
                            "old": old_val,
                            "new": new_val,
                        })
                if cell_changes:
                    row_changes.append({
                        "type": "modified",
                        "key": key,
                        "row": old_idx,
                        "cells": cell_changes,
                    })
            else:
                row_changes.append({
                    "type": "removed",
                    "key": key,
                    "row": old_by_key[key][0],
                    "data": [str(v) for v in old_by_key[key][1]],
                })

        for key in new_by_key:
            if key not in old_by_key:
                row_changes.append({
                    "type": "added",
                    "key": key,
                    "row": new_by_key[key][0],
                    "data": [str(v) for v in new_by_key[key][1]],
                })

    # Build summary
    summaries = []
    if added_cols:
        summaries.append(f"columns added: {', '.join(added_cols)}")
    if removed_cols:
        summaries.append(f"columns removed: {', '.join(removed_cols)}")
    mod_count = sum(1 for r in row_changes if r["type"] == "modified")
    add_count = sum(1 for r in row_changes if r["type"] == "added")
    rem_count = sum(1 for r in row_changes if r["type"] == "removed")
    if mod_count:
        summaries.append(f"{mod_count} rows modified")
    if add_count:
        summaries.append(f"{add_count} rows added")
    if rem_count:
        summaries.append(f"{rem_count} rows removed")

    has_changes = bool(added_cols or removed_cols or row_changes)

    return {
        "has_changes": has_changes,
        "summary": "; ".join(summaries) if summaries else "no changes",
        "column_changes": {
            "added": added_cols,
            "removed": removed_cols,
            "common": common_cols,
        },
        "row_changes": row_changes,
    }


def match_tables(old_tables: list[dict], new_tables: list[dict]) -> list[dict]:
    """
    Match tables between old and new documents by content similarity.

    Handles renumbering: if old "Table 1" has columns [A,B,C] and new "Table 2"
    has columns [A,B,C,D], they're matched by column overlap + row content similarity.

    Returns list of match pairs:
    [
        {"old": old_table, "new": new_table, "similarity": 0.85, "diff": {...}},
        {"old": old_table, "new": None},     # table removed
        {"old": None, "new": new_table},      # table added
    ]
    """
    if not old_tables and not new_tables:
        return []

    # Compute similarity matrix
    matches = []
    used_new = set()

    for old_t in old_tables:
        best_match = None
        best_sim = 0.0

        old_cols = set(str(c) for c in old_t.get("columns", []))
        old_flat = " ".join(str(v) for row in old_t.get("rows", []) for v in row)

        for j, new_t in enumerate(new_tables):
            if j in used_new:
                continue

            new_cols = set(str(c) for c in new_t.get("columns", []))
            new_flat = " ".join(str(v) for row in new_t.get("rows", []) for v in row)

            # Column similarity (Jaccard)
            col_union = old_cols | new_cols
            col_sim = len(old_cols & new_cols) / len(col_union) if col_union else 0

            # Content similarity
            content_sim = SequenceMatcher(
                None, old_flat[:1000], new_flat[:1000]
            ).ratio()

            # Combined score (weighted: columns matter more)
            combined = col_sim * 0.4 + content_sim * 0.6

            if combined > best_sim and combined > 0.3:
                best_sim = combined
                best_match = (j, new_t)

        if best_match:
            j, new_t = best_match
            used_new.add(j)
            diff = diff_tables(old_t, new_t)
            matches.append({
                "old": old_t,
                "new": new_t,
                "similarity": best_sim,
                "diff": diff,
            })
        else:
            matches.append({"old": old_t, "new": None, "similarity": 0.0, "diff": None})

    # Any unmatched new tables
    for j, new_t in enumerate(new_tables):
        if j not in used_new:
            matches.append({"old": None, "new": new_t, "similarity": 0.0, "diff": None})

    return matches


def diff_documents(old_path: str, new_path: str) -> dict:
    """
    Full structured diff between two PDFs using Docling.

    Returns:
    {
        "old_parsed": <parse_pdf result>,
        "new_parsed": <parse_pdf result>,
        "section_diffs": [...],   # section-level changes
        "table_matches": [...],   # table matching + cell-level diffs
        "summary": str,
    }
    """
    print(f"[docling] Parsing old document: {old_path}")
    t0 = time.time()
    old_parsed = parse_pdf(old_path)
    print(f"[docling] Old: {old_parsed['count']} sections, "
          f"{len(old_parsed['tables'])} tables, "
          f"{old_parsed['page_count']} pages in {time.time()-t0:.1f}s")

    print(f"[docling] Parsing new document: {new_path}")
    t1 = time.time()
    new_parsed = parse_pdf(new_path)
    print(f"[docling] New: {new_parsed['count']} sections, "
          f"{len(new_parsed['tables'])} tables, "
          f"{new_parsed['page_count']} pages in {time.time()-t1:.1f}s")

    # Section-level diff (by number/title matching)
    section_diffs = _diff_sections(old_parsed["sections"], new_parsed["sections"])

    # Table matching and cell-level diff
    table_matches = match_tables(old_parsed["tables"], new_parsed["tables"])

    # Summary
    mod_count = sum(1 for d in section_diffs if d["type"] == "MODIFIED")
    new_count = sum(1 for d in section_diffs if d["type"] == "NEW")
    rem_count = sum(1 for d in section_diffs if d["type"] == "REMOVED")
    table_changed = sum(1 for m in table_matches if m.get("diff") and m["diff"]["has_changes"])
    table_added = sum(1 for m in table_matches if m["old"] is None)
    table_removed = sum(1 for m in table_matches if m["new"] is None)

    summary = (
        f"Sections: {mod_count} modified, {new_count} new, {rem_count} removed. "
        f"Tables: {table_changed} modified, {table_added} added, {table_removed} removed."
    )

    return {
        "old_parsed": old_parsed,
        "new_parsed": new_parsed,
        "section_diffs": section_diffs,
        "table_matches": table_matches,
        "summary": summary,
    }


def _diff_sections(old_sections: list[dict], new_sections: list[dict]) -> list[dict]:
    """Diff sections by matching on number/title, then comparing text content."""
    # Build maps: number → section
    old_map = {}
    for s in old_sections:
        key = s["number"].lower().strip() if s["number"] else s["title"].lower().strip()
        old_map[key] = s

    new_map = {}
    for s in new_sections:
        key = s["number"].lower().strip() if s["number"] else s["title"].lower().strip()
        new_map[key] = s

    diffs = []

    # Check old sections against new
    for key, old_s in old_map.items():
        if key in new_map:
            new_s = new_map[key]
            old_text = old_s.get("text", "")
            new_text = new_s.get("text", "")
            sim = SequenceMatcher(None, old_text, new_text).ratio() if (old_text or new_text) else 1.0

            if sim < 0.98:
                diffs.append({
                    "type": "MODIFIED",
                    "old_section": old_s["number"] or old_s["title"],
                    "new_section": new_s["number"] or new_s["title"],
                    "similarity": sim,
                    "old_text_preview": old_text[:800],
                    "new_text_preview": new_text[:800],
                    "old_page": old_s["page"],
                    "new_page": new_s["page"],
                })
        else:
            diffs.append({
                "type": "REMOVED",
                "old_section": old_s["number"] or old_s["title"],
                "new_section": None,
                "similarity": 0.0,
                "old_text_preview": old_s.get("text", "")[:800],
                "new_text_preview": "",
                "old_page": old_s["page"],
                "new_page": None,
            })

    # New sections not in old
    for key, new_s in new_map.items():
        if key not in old_map:
            diffs.append({
                "type": "NEW",
                "old_section": None,
                "new_section": new_s["number"] or new_s["title"],
                "similarity": 0.0,
                "old_text_preview": "",
                "new_text_preview": new_s.get("text", "")[:800],
                "old_page": None,
                "new_page": new_s["page"],
            })

    return diffs


def _extract_section_number(heading_text: str) -> str:
    """Extract section number from heading like '1.2 Scope' → '1.2'."""
    m = re.match(r'^([\d]+(?:\.[\d]+)*)', heading_text.strip())
    if m:
        return m.group(1)
    # Check for "Table X", "Appendix X", etc.
    m = re.match(r'^((?:Table|Appendix|Figure|Annex)\s+[\w\d.]+)', heading_text.strip(), re.IGNORECASE)
    if m:
        return m.group(1)
    return heading_text.strip()[:30]


def _extract_section_title(heading_text: str) -> str:
    """Extract title part from heading like '1.2 Scope' → 'Scope'."""
    m = re.match(r'^[\d]+(?:\.[\d]+)*\s+(.*)', heading_text.strip())
    if m:
        return m.group(1).strip()
    m = re.match(r'^(?:Table|Appendix|Figure|Annex)\s+[\w\d.]+[:\s—-]*(.*)', heading_text.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return heading_text.strip()
