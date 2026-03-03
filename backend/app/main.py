"""
FastAPI application: upload, SSE progress, results, and PDF download endpoints.
"""
import asyncio
import json
import os
import shutil
import uuid
import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse, Response

from .config import CORS_ORIGINS, UPLOAD_DIR, MAX_FILE_SIZE, JOB_EXPIRY_SECONDS
from .agent import run_analysis
from .models import ProgressEvent

app = FastAPI(title="PDF by MK", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ── JOB STORAGE (in-memory) ────────────────────────────────────────

jobs: dict = {}
progress_queues: dict[str, asyncio.Queue] = {}


def cleanup_old_jobs():
    """Remove expired jobs."""
    now = time.time()
    expired = [jid for jid, j in jobs.items() if now - j.get("created_ts", 0) > JOB_EXPIRY_SECONDS]
    for jid in expired:
        job_dir = jobs[jid].get("job_dir")
        if job_dir and os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
        del jobs[jid]
        progress_queues.pop(jid, None)


# ── ENDPOINTS ───────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "jobs_active": len(jobs)}


@app.get("/api/health")
async def health():
    return {"status": "ok", "jobs_active": len(jobs)}


@app.post("/api/analyze")
async def start_analysis_endpoint(
    old_pdf: UploadFile = File(...),
    new_pdf: UploadFile = File(...),
    old_label: str = Form("Old Version"),
    new_label: str = Form("New Version"),
    api_key: Optional[str] = Form(None),
):
    """Upload two PDFs and start agentic analysis."""
    cleanup_old_jobs()

    # Validate files
    for f in [old_pdf, new_pdf]:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"File '{f.filename}' is not a PDF")
        if f.size and f.size > MAX_FILE_SIZE:
            raise HTTPException(400, f"File '{f.filename}' exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit")

    # Create job
    job_id = str(uuid.uuid4())[:12]
    job_dir = os.path.join(UPLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    old_path = os.path.join(job_dir, "old.pdf")
    new_path = os.path.join(job_dir, "new.pdf")

    # Save uploaded files
    with open(old_path, "wb") as f:
        content = await old_pdf.read()
        f.write(content)
    with open(new_path, "wb") as f:
        content = await new_pdf.read()
        f.write(content)

    # Initialize job
    jobs[job_id] = {
        "status": "processing",
        "created_at": datetime.utcnow().isoformat(),
        "created_ts": time.time(),
        "old_label": old_label,
        "new_label": new_label,
        "job_dir": job_dir,
        "old_pdf_path": old_path,
        "new_pdf_path": new_path,
        "progress": [],
        "result": None,
        "error": None,
    }

    progress_queues[job_id] = asyncio.Queue()

    # Start analysis in background — runs in the main event loop (no thread)
    asyncio.create_task(_run_job(job_id, old_path, new_path, old_label, new_label, api_key or ""))

    return {
        "job_id": job_id,
        "status": "processing",
        "progress_url": f"/api/analyze/{job_id}/progress",
    }


async def _run_job(job_id, old_path, new_path, old_label, new_label, api_key):
    """Background task for running the analysis."""
    async def progress_cb(event: ProgressEvent):
        event_dict = event.model_dump()
        jobs[job_id]["progress"].append(event_dict)
        if job_id in progress_queues:
            await progress_queues[job_id].put(event_dict)

    try:
        result = await run_analysis(
            job_id, old_path, new_path, old_label, new_label, api_key, progress_cb
        )
        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result

        # Signal completion through queue
        if job_id in progress_queues:
            await progress_queues[job_id].put({
                "stage": "complete", "percent": 100,
                "message": f"Analysis complete: {result['total_changes']} changes found",
            })
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
        if job_id in progress_queues:
            await progress_queues[job_id].put({
                "stage": "failed", "percent": 0, "message": str(e),
            })


@app.get("/api/analyze/{job_id}/progress")
async def stream_progress(job_id: str):
    """Server-Sent Events endpoint for real-time progress."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    async def event_generator():
        # Send existing progress first
        for event in jobs[job_id].get("progress", []):
            yield f"event: progress\ndata: {json.dumps(event)}\n\n"

        # If already done, send final event and close
        status = jobs[job_id]["status"]
        if status == "completed":
            result = jobs[job_id].get("result", {})
            yield f"event: complete\ndata: {json.dumps({'status': 'completed', 'total_changes': result.get('total_changes', 0)})}\n\n"
            return
        elif status == "failed":
            yield f"event: failed\ndata: {json.dumps({'status': 'failed', 'error': jobs[job_id].get('error', 'Unknown error')})}\n\n"
            return

        # Listen for new events
        queue = progress_queues.get(job_id)
        if not queue:
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                stage = event.get("stage", "")
                if stage == "complete":
                    yield f"event: complete\ndata: {json.dumps(event)}\n\n"
                    break
                elif stage == "failed":
                    yield f"event: failed\ndata: {json.dumps(event)}\n\n"
                    break
                else:
                    yield f"event: progress\ndata: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment (not an event)
                yield f": keepalive\n\n"
                # Check if job finished while we were waiting
                if jobs[job_id]["status"] in ("completed", "failed"):
                    status = jobs[job_id]["status"]
                    if status == "completed":
                        result = jobs[job_id].get("result", {})
                        yield f"event: complete\ndata: {json.dumps({'status': 'completed', 'total_changes': result.get('total_changes', 0)})}\n\n"
                    else:
                        yield f"event: failed\ndata: {json.dumps({'status': 'failed', 'error': jobs[job_id].get('error', '')})}\n\n"
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/analyze/{job_id}/result")
async def get_result(job_id: str):
    """Get the complete analysis result."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    job = jobs[job_id]
    if job["status"] == "processing":
        return JSONResponse({"status": "processing", "progress": job["progress"]}, status_code=202)

    if job["status"] == "failed":
        return JSONResponse({"status": "failed", "error": job["error"]}, status_code=200)

    result = job["result"]
    return {
        "job_id": job_id,
        "status": "completed",
        "created_at": job["created_at"],
        "old_label": job["old_label"],
        "new_label": job["new_label"],
        "total_changes": result["total_changes"],
        "by_category": result["by_category"],
        "by_impact": result["by_impact"],
        "changes": result["changes"],
        "manifest": result.get("manifest"),
    }


@app.get("/api/analyze/{job_id}/pdf/{which}")
async def serve_pdf(job_id: str, which: str):
    """Serve annotated PDF inline in browser."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    job = jobs[job_id]
    result = job.get("result")
    if not result:
        raise HTTPException(400, "Analysis not complete")

    if which == "old":
        path = result.get("old_annotated_path")
        filename = f"{job['old_label']}_ANNOTATED.pdf"
    elif which == "new":
        path = result.get("new_annotated_path")
        filename = f"{job['new_label']}_ANNOTATED.pdf"
    else:
        raise HTTPException(400, "Invalid PDF type. Use 'old' or 'new'.")

    if not path or not os.path.exists(path):
        raise HTTPException(404, "Annotated PDF not found")

    # Read file and return with inline Content-Disposition
    with open(path, "rb") as f:
        pdf_bytes = f.read()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
