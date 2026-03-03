"""Tests for pdf_utils module — extraction, search, sections, diff, annotation."""
import os
import pytest
from app.pdf_utils import (
    extract_full_text,
    extract_page_text,
    detect_sections,
    detect_revision_history,
    search_document,
    diff_sections,
    annotate_pdf,
)


class TestExtractFullText:
    def test_basic_extraction(self, tiny_pdf):
        result = extract_full_text(tiny_pdf)
        assert result["total_pages"] == 1
        assert result["total_chars"] > 0
        assert len(result["pages"]) == 1
        assert "Introduction" in result["full_text"]
        assert "Hello world" in result["full_text"]

    def test_page_structure(self, tiny_pdf):
        result = extract_full_text(tiny_pdf)
        page = result["pages"][0]
        assert page["page"] == 1
        assert page["char_count"] > 0
        assert isinstance(page["text"], str)

    @pytest.mark.skipif(
        not os.path.exists("/sessions/brave-gifted-babbage/mnt/Claude/PDF compare/AEC-Q101_Rev_E_2021.pdf"),
        reason="Sample PDF not available",
    )
    def test_real_pdf_extraction(self, sample_pdf_pair):
        old_pdf, new_pdf = sample_pdf_pair
        result = extract_full_text(old_pdf)
        assert result["total_pages"] > 10
        assert result["total_chars"] > 10000
        assert "AEC" in result["full_text"] or "qualification" in result["full_text"].lower()


class TestExtractPageText:
    def test_valid_page(self, tiny_pdf):
        result = extract_page_text(tiny_pdf, 1)
        assert result["page"] == 1
        assert "Introduction" in result["text"]

    def test_out_of_range(self, tiny_pdf):
        result = extract_page_text(tiny_pdf, 999)
        assert "error" in result

    def test_page_zero(self, tiny_pdf):
        result = extract_page_text(tiny_pdf, 0)
        assert "error" in result


class TestDetectSections:
    def test_finds_numbered_sections(self, tiny_pdf):
        result = detect_sections(tiny_pdf)
        assert result["count"] >= 1
        numbers = [s["number"] for s in result["sections"]]
        assert "1" in numbers or "2" in numbers or "3" in numbers

    @pytest.mark.skipif(
        not os.path.exists("/sessions/brave-gifted-babbage/mnt/Claude/PDF compare/AEC-Q101_Rev_E_2021.pdf"),
        reason="Sample PDF not available",
    )
    def test_real_pdf_sections(self, sample_pdf_pair):
        _, new_pdf = sample_pdf_pair
        result = detect_sections(new_pdf)
        assert result["count"] > 5  # Real doc should have many sections


class TestSearchDocument:
    def test_finds_existing_text(self, tiny_pdf):
        result = search_document(tiny_pdf, "Introduction")
        assert result["total_matches"] >= 1
        assert result["results"][0]["page"] == 1

    def test_returns_context(self, tiny_pdf):
        result = search_document(tiny_pdf, "Hello world")
        assert result["total_matches"] >= 1
        assert "context" in result["results"][0]

    def test_no_matches(self, tiny_pdf):
        result = search_document(tiny_pdf, "xyznonexistent")
        assert result["total_matches"] == 0

    def test_case_insensitive(self, tiny_pdf):
        result = search_document(tiny_pdf, "introduction")
        assert result["total_matches"] >= 1

    @pytest.mark.skipif(
        not os.path.exists("/sessions/brave-gifted-babbage/mnt/Claude/PDF compare/AEC-Q101_Rev_E_2021.pdf"),
        reason="Sample PDF not available",
    )
    def test_real_pdf_search(self, sample_pdf_pair):
        old_pdf, _ = sample_pdf_pair
        result = search_document(old_pdf, "qualification")
        assert result["total_matches"] >= 1


class TestDiffSections:
    def test_detects_modifications(self, two_tiny_pdfs):
        old_path, new_path = two_tiny_pdfs
        result = diff_sections(old_path, new_path)
        assert result["total_diffs"] >= 1
        types = [d["type"] for d in result["diffs"]]
        # Should detect at least one modification (Introduction or Results changed)
        assert "MODIFIED" in types or "NEW" in types

    def test_detects_new_section(self, two_tiny_pdfs):
        old_path, new_path = two_tiny_pdfs
        result = diff_sections(old_path, new_path)
        new_diffs = [d for d in result["diffs"] if d["type"] == "NEW"]
        # Section 4 (Conclusions) is new
        new_sections = [d["new_section"] for d in new_diffs]
        assert "4" in new_sections or any("4" in str(s) for s in new_sections)

    def test_returns_section_counts(self, two_tiny_pdfs):
        old_path, new_path = two_tiny_pdfs
        result = diff_sections(old_path, new_path)
        assert "old_sections" in result
        assert "new_sections" in result
        assert result["new_sections"] >= result["old_sections"]


class TestAnnotatePdf:
    def test_creates_annotated_file(self, tiny_pdf, tmp_path):
        output = str(tmp_path / "annotated.pdf")
        annotations = [{"change_id": 1, "search_text": "Introduction"}]
        result = annotate_pdf(tiny_pdf, output, annotations)
        assert os.path.exists(output)
        assert result["highlights"] >= 1

    def test_page_map(self, tiny_pdf, tmp_path):
        output = str(tmp_path / "annotated.pdf")
        annotations = [{"change_id": 1, "search_text": "Introduction"}]
        result = annotate_pdf(tiny_pdf, output, annotations)
        assert 1 in result["page_map"]
        assert result["page_map"][1] == 1

    def test_empty_annotations(self, tiny_pdf, tmp_path):
        output = str(tmp_path / "annotated.pdf")
        result = annotate_pdf(tiny_pdf, output, [])
        assert os.path.exists(output)
        assert result["highlights"] == 0

    def test_fallback_shorter_snippet(self, tiny_pdf, tmp_path):
        output = str(tmp_path / "annotated.pdf")
        # Use text that's long enough to trigger the fallback logic
        annotations = [{"change_id": 1, "search_text": "This is very long text that does not exist anywhere in the document at all xxxxx"}]
        result = annotate_pdf(tiny_pdf, output, annotations)
        assert os.path.exists(output)


class TestDetectRevisionHistory:
    def test_no_history_in_simple_pdf(self, tiny_pdf):
        result = detect_revision_history(tiny_pdf)
        assert result["detected"] is False

    @pytest.mark.skipif(
        not os.path.exists("/sessions/brave-gifted-babbage/mnt/Claude/PDF compare/AEC-Q101_Rev_E_2021.pdf"),
        reason="Sample PDF not available",
    )
    def test_real_pdf_has_manifest(self, sample_pdf_pair):
        _, new_pdf = sample_pdf_pair
        result = detect_revision_history(new_pdf)
        # AEC-Q101 Rev E should have revision history
        assert result["detected"] is True
        assert len(result["pages"]) >= 1
