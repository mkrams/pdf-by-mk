"""Tests for FastAPI endpoints."""
import os
import io
import time
import pytest
import fitz
from fastapi.testclient import TestClient
from app.main import app, jobs, progress_queues


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear jobs between tests."""
    jobs.clear()
    progress_queues.clear()
    yield
    jobs.clear()
    progress_queues.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def pdf_bytes():
    """Generate a minimal PDF as bytes."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "1 Introduction\nHello World.\n2 Methods\nTest method.")
    buf = doc.tobytes()
    doc.close()
    return buf


def upload_pair(client, pdf_bytes, **extra_data):
    """Helper to upload a PDF pair."""
    data = {"old_label": "Old", "new_label": "New"}
    data.update(extra_data)
    return client.post(
        "/api/analyze",
        files=[
            ("old_pdf", ("old.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ("new_pdf", ("new.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
        ],
        data=data,
    )


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "jobs_active" in data


class TestAnalyzeUpload:
    def test_upload_pdfs(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes)
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"
        assert "progress_url" in data

    def test_reject_non_pdf(self, client, pdf_bytes):
        resp = client.post(
            "/api/analyze",
            files=[
                ("old_pdf", ("old.txt", io.BytesIO(b"not a pdf"), "text/plain")),
                ("new_pdf", ("new.pdf", io.BytesIO(pdf_bytes), "application/pdf")),
            ],
        )
        assert resp.status_code == 400

    def test_upload_creates_job(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes)
        job_id = resp.json()["job_id"]
        assert job_id in jobs
        # Status may be "processing" or "failed" (no API key in test env)
        assert jobs[job_id]["status"] in ("processing", "failed")

    def test_labels_stored(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes, old_label="RevA", new_label="RevB")
        job_id = resp.json()["job_id"]
        assert jobs[job_id]["old_label"] == "RevA"
        assert jobs[job_id]["new_label"] == "RevB"


class TestResultEndpoint:
    def test_nonexistent_job(self, client):
        resp = client.get("/api/analyze/nonexistent/result")
        assert resp.status_code == 404

    def test_processing_job(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes)
        job_id = resp.json()["job_id"]
        result_resp = client.get(f"/api/analyze/{job_id}/result")
        # Should be 202 (still processing) or 500 (failed because no API key)
        assert result_resp.status_code in (202, 500)


class TestPdfDownload:
    def test_nonexistent_job(self, client):
        resp = client.get("/api/analyze/nonexistent/pdf/old")
        assert resp.status_code == 404

    def test_invalid_which(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes)
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/analyze/{job_id}/pdf/invalid")
        assert resp.status_code == 400

    def test_not_complete(self, client, pdf_bytes):
        resp = upload_pair(client, pdf_bytes)
        job_id = resp.json()["job_id"]
        resp = client.get(f"/api/analyze/{job_id}/pdf/old")
        assert resp.status_code == 400  # Analysis not complete


class TestProgressSSE:
    def test_nonexistent_job(self, client):
        resp = client.get("/api/analyze/nonexistent/progress")
        assert resp.status_code == 404
