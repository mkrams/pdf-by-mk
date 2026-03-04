from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChangeItem(BaseModel):
    id: int
    section: str
    title: str
    category: str  # NEW, MODIFIED, REMOVED, STRUCTURAL, FORMATTING
    description: str
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    impact: str  # "HIGH — explanation..."
    impact_level: str  # CRITICAL, HIGH, MEDIUM, LOW
    manifest_item: Optional[str] = None
    verification_status: Optional[str] = None
    verification_conclusion: Optional[str] = None
    verification_keywords: list[str] = []
    old_page: Optional[int] = None
    new_page: Optional[int] = None


class ManifestInfo(BaseModel):
    detected: bool = False
    source: Optional[str] = None  # "old_pdf" or "new_pdf"
    page: Optional[int] = None
    revised: list[str] = []
    added: list[str] = []
    deleted: list[str] = []


class AnalysisResult(BaseModel):
    job_id: str
    status: str  # queued, processing, completed, failed
    created_at: str
    old_label: str = "Old Version"
    new_label: str = "New Version"
    total_changes: int = 0
    by_category: dict = {}
    by_impact: dict = {}
    changes: list[ChangeItem] = []
    manifest: Optional[ManifestInfo] = None
    error: Optional[str] = None


class CandidateChange(BaseModel):
    """Lightweight candidate change identified by the orchestrator."""
    id: str                         # e.g. "C001"
    section: str                    # e.g. "2.3", "Table 3"
    title: str                      # Brief description
    category_hint: str              # From diff: MODIFIED, NEW, REMOVED
    old_pages: list[int] = []       # Pages to read from old PDF
    new_pages: list[int] = []       # Pages to read from new PDF
    diff_preview: str = ""          # First ~200 chars of the diff
    manifest_item: Optional[str] = None  # Matching manifest entry if any


class ProgressEvent(BaseModel):
    stage: str
    percent: int = 0
    message: str = ""       # Human-readable message (e.g., "Mapping document structures")
    turn: int = 0           # Current AI turn
    max_turns: int = 15     # Max AI turns
    tokens: int = 0         # Total tokens used
    elapsed: int = 0        # Seconds elapsed
    changes_found: int = 0
    candidates_found: int = 0
    old_pages_count: int = 0
    new_pages_count: int = 0
    timestamp: str = ""
