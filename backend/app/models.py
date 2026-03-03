from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChangeItem(BaseModel):
    id: int
    section: str
    title: str
    category: str  # NEW, MODIFIED, REMOVED, STRUCTURAL
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


class ProgressEvent(BaseModel):
    stage: str
    percent: int = 0
    message: str = ""
    changes_found: int = 0
    timestamp: str = ""
