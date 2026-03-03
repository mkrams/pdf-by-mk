"""Tests for tool definitions and execution."""
import json
import pytest
from app.tools import TOOL_DEFINITIONS, execute_tool


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_correct_tool_count(self):
        assert len(TOOL_DEFINITIONS) == 8

    def test_tool_names(self):
        names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "extract_pdf_text", "extract_pdf_page", "detect_document_structure",
            "detect_revision_history", "search_document", "diff_sections",
            "report_progress", "submit_changes",
        }
        assert names == expected


class TestExecuteTool:
    def test_extract_pdf_text(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("extract_pdf_text", {"pdf_id": "old"}, ctx))
        assert result["total_pages"] == 1
        assert "full_text" not in result  # Stripped to save tokens
        assert "Introduction" in result["pages"][0]["text"]

    def test_extract_pdf_page(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("extract_pdf_page", {"pdf_id": "new", "page_number": 1}, ctx))
        assert "text" in result

    def test_detect_document_structure(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("detect_document_structure", {"pdf_id": "old"}, ctx))
        assert "sections" in result

    def test_detect_revision_history(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("detect_revision_history", {"pdf_id": "old"}, ctx))
        assert "detected" in result

    def test_search_document(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("search_document", {"pdf_id": "old", "query": "Introduction"}, ctx))
        assert result["total_matches"] >= 1

    def test_diff_sections(self, two_tiny_pdfs):
        old, new = two_tiny_pdfs
        ctx = {"old_pdf_path": old, "new_pdf_path": new}
        result = json.loads(execute_tool("diff_sections", {}, ctx))
        assert "total_diffs" in result

    def test_report_progress(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("report_progress", {"stage": "test", "message": "testing"}, ctx))
        assert result["status"] == "reported"

    def test_submit_changes(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        changes = [{"section": "1", "title": "Test", "category": "MODIFIED", "description": "test", "impact": "LOW"}]
        result = json.loads(execute_tool("submit_changes", {"changes": changes}, ctx))
        assert result["status"] == "submitted"
        assert result["change_count"] == 1
        assert ctx["submitted_changes"] == changes

    def test_unknown_tool(self, tiny_pdf):
        ctx = {"old_pdf_path": tiny_pdf, "new_pdf_path": tiny_pdf}
        result = json.loads(execute_tool("nonexistent_tool", {}, ctx))
        assert "error" in result
