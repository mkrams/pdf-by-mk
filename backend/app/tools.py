"""
Tool definitions for the Claude agent, and their server-side execution.
"""
import json
from . import pdf_utils

# ── TOOL DEFINITIONS (Claude API format) ────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "extract_pdf_text",
        "description": (
            "Extract all text from a PDF file. Returns page-by-page text with character counts. "
            "Use this first to understand the content of both documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {
                    "type": "string",
                    "enum": ["old", "new"],
                    "description": "Which PDF to extract: 'old' or 'new'",
                },
            },
            "required": ["pdf_id"],
        },
    },
    {
        "name": "extract_pdf_page",
        "description": "Extract text from a specific page of a PDF. Use for targeted reading.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
                "page_number": {"type": "integer", "description": "1-indexed page number"},
            },
            "required": ["pdf_id", "page_number"],
        },
    },
    {
        "name": "detect_document_structure",
        "description": (
            "Parse document structure — detect section headings, tables, appendices. "
            "Returns list of sections with numbers, titles, and page numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
            },
            "required": ["pdf_id"],
        },
    },
    {
        "name": "detect_revision_history",
        "description": (
            "Scan a PDF for a revision history, change manifest, or change log. "
            "Checks first and last pages for sections listing revised/added/deleted items. "
            "If found, returns the manifest items categorized. This is critical for "
            "verification — if the document has its own list of changes, we should use it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
            },
            "required": ["pdf_id"],
        },
    },
    {
        "name": "search_document",
        "description": (
            "Search for specific text in a PDF. Returns all matches with page numbers "
            "and surrounding context. Use this to:\n"
            "- Verify NEW items don't exist in the old document\n"
            "- Verify REMOVED items don't appear in the new document\n"
            "- Find where specific text appears"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "string", "enum": ["old", "new"]},
                "query": {"type": "string", "description": "Text to search for"},
            },
            "required": ["pdf_id", "query"],
        },
    },
    {
        "name": "diff_sections",
        "description": (
            "Run a systematic section-by-section diff between old and new PDFs. "
            "Returns list of differences with type (MODIFIED/NEW/REMOVED), "
            "similarity score, and text previews. Use section_map if sections were renumbered."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section_map": {
                    "type": "object",
                    "description": (
                        "Optional mapping of old section numbers to new section numbers "
                        "if the document was restructured. E.g. {'2.4': '2.3', '2.5': '2.4'}"
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "report_progress",
        "description": "Report progress to the user. Call this frequently so they can see what you're doing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "description": "Current stage name",
                },
                "percent": {
                    "type": "integer",
                    "description": "Progress percentage (0-100)",
                },
                "message": {
                    "type": "string",
                    "description": "Human-readable status message",
                },
            },
            "required": ["stage", "message"],
        },
    },
    {
        "name": "submit_changes",
        "description": (
            "Submit the final change register. Call this when you have identified, "
            "classified, verified, and assessed all changes. Each change needs: "
            "section, title, category, description, old_text, new_text, impact, "
            "verification_status, and verification_conclusion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string"},
                            "title": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": ["NEW", "MODIFIED", "REMOVED", "STRUCTURAL"],
                            },
                            "description": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "impact": {"type": "string", "description": "LEVEL — explanation"},
                            "manifest_item": {"type": "string"},
                            "verification_status": {"type": "string"},
                            "verification_conclusion": {"type": "string"},
                            "verification_keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "search_old": {"type": "string", "description": "Snippet to find in old PDF for annotation"},
                            "search_new": {"type": "string", "description": "Snippet to find in new PDF for annotation"},
                        },
                        "required": ["section", "title", "category", "description", "impact"],
                    },
                },
                "manifest": {
                    "type": "object",
                    "description": "Manifest info if detected",
                    "properties": {
                        "detected": {"type": "boolean"},
                        "source": {"type": "string"},
                        "revised": {"type": "array", "items": {"type": "string"}},
                        "added": {"type": "array", "items": {"type": "string"}},
                        "deleted": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["changes"],
        },
    },
]


# ── TOOL EXECUTION ──────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_input: dict, job_context: dict) -> str:
    """Execute a tool and return JSON result string."""
    old_pdf = job_context["old_pdf_path"]
    new_pdf = job_context["new_pdf_path"]

    try:
        if tool_name == "extract_pdf_text":
            pdf_path = old_pdf if tool_input["pdf_id"] == "old" else new_pdf
            result = pdf_utils.extract_full_text(pdf_path)
            # Aggressively truncate — only return first 500 chars per page
            # Agent should use extract_pdf_page for detailed reading
            for p in result["pages"]:
                if len(p["text"]) > 500:
                    p["text"] = p["text"][:500] + f"\n... [truncated, use extract_pdf_page for full text]"
            # Drop full_text to save tokens
            result.pop("full_text", None)
            return json.dumps(result)

        elif tool_name == "extract_pdf_page":
            pdf_path = old_pdf if tool_input["pdf_id"] == "old" else new_pdf
            result = pdf_utils.extract_page_text(pdf_path, tool_input["page_number"])
            return json.dumps(result)

        elif tool_name == "detect_document_structure":
            pdf_path = old_pdf if tool_input["pdf_id"] == "old" else new_pdf
            result = pdf_utils.detect_sections(pdf_path)
            return json.dumps(result)

        elif tool_name == "detect_revision_history":
            pdf_path = old_pdf if tool_input["pdf_id"] == "old" else new_pdf
            result = pdf_utils.detect_revision_history(pdf_path)
            return json.dumps(result)

        elif tool_name == "search_document":
            pdf_path = old_pdf if tool_input["pdf_id"] == "old" else new_pdf
            result = pdf_utils.search_document(pdf_path, tool_input["query"])
            return json.dumps(result)

        elif tool_name == "diff_sections":
            section_map = tool_input.get("section_map")
            result = pdf_utils.diff_sections(old_pdf, new_pdf, section_map)
            # Aggressively truncate diffs and text previews
            for d in result["diffs"]:
                if "diff_preview" in d and len(d["diff_preview"]) > 600:
                    d["diff_preview"] = d["diff_preview"][:600] + "\n..."
                if "old_text_preview" in d and len(d["old_text_preview"]) > 300:
                    d["old_text_preview"] = d["old_text_preview"][:300] + "..."
                if "new_text_preview" in d and len(d["new_text_preview"]) > 300:
                    d["new_text_preview"] = d["new_text_preview"][:300] + "..."
            return json.dumps(result)

        elif tool_name == "report_progress":
            # Progress is handled by the agent orchestrator, not here
            return json.dumps({"status": "reported"})

        elif tool_name == "submit_changes":
            # Store changes in job context for the orchestrator to pick up
            raw_changes = tool_input.get("changes", [])
            # Defensive: ensure changes is a list of dicts
            if isinstance(raw_changes, str):
                try:
                    raw_changes = json.loads(raw_changes)
                except (json.JSONDecodeError, TypeError):
                    raw_changes = []
            if not isinstance(raw_changes, list):
                raw_changes = []
            # Filter out any non-dict items
            validated = [c for c in raw_changes if isinstance(c, dict)]
            job_context["submitted_changes"] = validated
            raw_manifest = tool_input.get("manifest")
            if isinstance(raw_manifest, str):
                try:
                    raw_manifest = json.loads(raw_manifest)
                except (json.JSONDecodeError, TypeError):
                    raw_manifest = None
            job_context["submitted_manifest"] = raw_manifest
            return json.dumps({"status": "submitted", "change_count": len(validated)})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})
