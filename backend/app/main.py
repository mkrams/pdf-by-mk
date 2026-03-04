"""
FastAPI application: upload, SSE progress, results, and PDF download endpoints.
"""
import asyncio
import json
import os
import queue as thread_queue  # thread-safe queue
import shutil
import uuid
import time
import traceback
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response

from .config import CORS_ORIGINS, UPLOAD_DIR, MAX_FILE_SIZE, JOB_EXPIRY_SECONDS
from .orchestrator import run_orchestrator
from .mini_agent import run_mini_agent
from .models import ProgressEvent, ChangeItem
from .pdf_utils import render_page_image, get_page_count, annotate_pdf

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
# Thread-safe queues — can be written from worker threads, read from async SSE
progress_queues: dict[str, thread_queue.Queue] = {}


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

    progress_queues[job_id] = thread_queue.Queue()

    # Start analysis in background thread
    asyncio.create_task(_run_job(job_id, old_path, new_path, old_label, new_label, api_key or ""))

    return {
        "job_id": job_id,
        "status": "processing",
        "progress_url": f"/api/analyze/{job_id}/progress",
    }


MINI_AGENT_BATCH_SIZE = 3  # How many mini-agents to run in parallel (kept low for Railway memory)


async def _run_job(job_id, old_path, new_path, old_label, new_label, api_key):
    """
    Two-phase analysis pipeline:
    Phase 1: Orchestrator identifies candidates (fast, mostly programmatic)
    Phase 2: Mini-agents analyze each candidate (parallel, streamed)
    Phase 3: Annotation (batch)
    """
    start_time = time.time()
    all_changes = []  # Accumulated classified changes
    total_tokens = 0
    change_id_counter = [0]  # mutable for closure

    def progress_cb(event: ProgressEvent):
        """SYNC callback — called from worker threads."""
        event_dict = event.model_dump()
        jobs[job_id]["progress"].append(event_dict)
        if job_id in progress_queues:
            progress_queues[job_id].put(event_dict)

    def emit_change(change_dict):
        """SYNC callback — called when a mini-agent classifies a change."""
        change_id_counter[0] += 1
        change_dict["id"] = change_id_counter[0]
        all_changes.append(change_dict)

        # Stream to frontend immediately
        if job_id in progress_queues:
            progress_queues[job_id].put({
                "event_type": "change_found",
                "change": change_dict,
            })

    try:
        # ── PHASE 1: ORCHESTRATOR ──────────────────────────────────────
        jobs[job_id]["phase"] = "orchestrator"
        print(f"[job {job_id}] Phase 1: Orchestrator starting...")

        orch_result = await asyncio.to_thread(
            run_orchestrator,
            job_id, old_path, new_path, old_label, new_label, api_key, progress_cb,
        )

        candidates = orch_result.get("candidates", [])
        manifest_data = orch_result.get("manifest")
        page_cache = orch_result.get("page_cache", {})
        total_tokens += orch_result.get("tokens_used", 0)

        print(f"[job {job_id}] Phase 1 complete: {len(candidates)} candidates, "
              f"{len(page_cache)} pages cached")

        if not candidates:
            # No changes found — still complete successfully
            progress_cb(ProgressEvent(
                stage="complete", percent=100,
                message="No changes detected between documents",
                changes_found=0,
            ))
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["result"] = _build_empty_result(old_path, new_path)
            if job_id in progress_queues:
                progress_queues[job_id].put({
                    "stage": "complete", "percent": 100,
                    "message": "No changes detected",
                })
            return

        # ── PHASE 2: MINI-AGENTS ───────────────────────────────────────
        jobs[job_id]["phase"] = "mini_agents"
        print(f"[job {job_id}] Phase 2: Running {len(candidates)} mini-agents...")

        # Batch candidates for parallel execution
        batches = [
            candidates[i:i + MINI_AGENT_BATCH_SIZE]
            for i in range(0, len(candidates), MINI_AGENT_BATCH_SIZE)
        ]

        for batch_num, batch in enumerate(batches):
            progress_cb(ProgressEvent(
                stage="mini_agents",
                percent=20 + int((batch_num / len(batches)) * 60),
                message=f"Analyzing batch {batch_num + 1} of {len(batches)} "
                        f"({len(all_changes)} changes found so far)",
                changes_found=len(all_changes),
                candidates_found=len(candidates),
                elapsed=int(time.time() - start_time),
            ))

            # Run mini-agents in parallel within this batch
            async def run_one(cand):
                return await asyncio.to_thread(
                    run_mini_agent,
                    job_id, cand, page_cache, old_path, new_path, api_key, emit_change,
                )

            results = await asyncio.gather(
                *[run_one(cand) for cand in batch],
                return_exceptions=True,
            )

            # Process results
            for result in results:
                if isinstance(result, Exception):
                    print(f"[job {job_id}] Mini-agent exception: {result}")
                    continue
                total_tokens += result.get("tokens_used", 0)
                if result.get("error"):
                    print(f"[job {job_id}] Mini-agent {result['agent_id']} error: {result['error']}")

            # Free page cache entries consumed by this batch to reduce memory
            for cand in batch:
                for p in cand.get("old_pages", []):
                    page_cache.pop(("old", p), None)
                for p in cand.get("new_pages", []):
                    page_cache.pop(("new", p), None)

            print(f"[job {job_id}] Batch {batch_num + 1}/{len(batches)} done. "
                  f"Changes so far: {len(all_changes)}")

        print(f"[job {job_id}] Phase 2 complete: {len(all_changes)} changes classified, "
              f"{total_tokens:,} tokens total")

        # ── PHASE 3: ANNOTATION ────────────────────────────────────────
        jobs[job_id]["phase"] = "annotation"
        progress_cb(ProgressEvent(
            stage="annotating", percent=85,
            message=f"Annotating {len(all_changes)} changes in PDFs...",
            changes_found=len(all_changes),
            elapsed=int(time.time() - start_time),
        ))

        # Build annotation data
        old_annotations = []
        new_annotations = []
        for c in all_changes:
            cid = c.get("id", 0)
            if c.get("search_old"):
                old_annotations.append({"change_id": cid, "search_text": c["search_old"]})
            if c.get("search_new"):
                new_annotations.append({"change_id": cid, "search_text": c["search_new"]})

        job_dir = os.path.dirname(old_path)
        old_ann_path = os.path.join(job_dir, "old_annotated.pdf")
        new_ann_path = os.path.join(job_dir, "new_annotated.pdf")

        old_ann_result = await asyncio.to_thread(annotate_pdf, old_path, old_ann_path, old_annotations)
        new_ann_result = await asyncio.to_thread(annotate_pdf, new_path, new_ann_path, new_annotations)

        print(f"[job {job_id}] Annotation: {old_ann_result['highlights']} old + "
              f"{new_ann_result['highlights']} new highlights")

        # ── BUILD FINAL RESULT ─────────────────────────────────────────
        final_changes = []
        for c in all_changes:
            cid = c.get("id", 0)
            impact_raw = c.get("impact", "MEDIUM") or "MEDIUM"
            impact_level = impact_raw.split(" ")[0].split("—")[0].strip().upper()
            if impact_level not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                impact_level = "MEDIUM"

            final_changes.append(ChangeItem(
                id=cid,
                section=c.get("section", ""),
                title=c.get("title", ""),
                category=c.get("category", "MODIFIED"),
                description=c.get("description", ""),
                old_text=c.get("old_text"),
                new_text=c.get("new_text"),
                impact=impact_raw,
                impact_level=impact_level,
                manifest_item=c.get("manifest_item"),
                verification_status=c.get("verification_status"),
                verification_conclusion=c.get("verification_conclusion"),
                verification_keywords=c.get("verification_keywords", []),
                old_page=old_ann_result["page_map"].get(cid),
                new_page=new_ann_result["page_map"].get(cid),
            ))

        by_category = {}
        by_impact = {}
        for c in final_changes:
            by_category[c.category] = by_category.get(c.category, 0) + 1
            by_impact[c.impact_level] = by_impact.get(c.impact_level, 0) + 1

        elapsed = int(time.time() - start_time)
        mins, secs = divmod(elapsed, 60)

        result = {
            "changes": [c.model_dump() for c in final_changes],
            "total_changes": len(final_changes),
            "by_category": by_category,
            "by_impact": by_impact,
            "manifest": manifest_data,
            "old_annotated_path": old_ann_path,
            "new_annotated_path": new_ann_path,
        }

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["result"] = result

        print(f"[job {job_id}] COMPLETE: {len(final_changes)} changes in {mins}:{secs:02d}, "
              f"{total_tokens:,} tokens")

        if job_id in progress_queues:
            progress_queues[job_id].put({
                "stage": "complete", "percent": 100,
                "message": f"Done in {mins}:{secs:02d} — {len(final_changes)} changes, "
                           f"{total_tokens:,} tokens",
            })

    except Exception as e:
        tb = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {str(e)}"
        print(f"[job {job_id}] FAILED:\n{tb}")
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = error_msg
        if job_id in progress_queues:
            progress_queues[job_id].put({
                "stage": "failed", "percent": 0, "message": error_msg,
            })


def _build_empty_result(old_path, new_path):
    """Build an empty result when no changes are found."""
    job_dir = os.path.dirname(old_path)
    return {
        "changes": [],
        "total_changes": 0,
        "by_category": {},
        "by_impact": {},
        "manifest": None,
        "old_annotated_path": old_path,
        "new_annotated_path": new_path,
    }


@app.get("/api/analyze/{job_id}/progress")
async def stream_progress(job_id: str):
    """Server-Sent Events endpoint for real-time progress."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    async def event_generator():
        # Send existing progress first (catch-up for late SSE connections)
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

        # Stream new events from the thread-safe queue
        q = progress_queues.get(job_id)
        if not q:
            return

        while True:
            # Poll the thread-safe queue without blocking the event loop
            try:
                event = q.get_nowait()
            except thread_queue.Empty:
                # No new events — check if job finished
                if jobs[job_id]["status"] in ("completed", "failed"):
                    status = jobs[job_id]["status"]
                    if status == "completed":
                        result = jobs[job_id].get("result", {})
                        yield f"event: complete\ndata: {json.dumps({'status': 'completed', 'total_changes': result.get('total_changes', 0)})}\n\n"
                    else:
                        yield f"event: failed\ndata: {json.dumps({'status': 'failed', 'error': jobs[job_id].get('error', '')})}\n\n"
                    break
                # Wait a bit before polling again
                await asyncio.sleep(0.5)
                continue

            # Got an event from the queue
            event_type = event.get("event_type")
            stage = event.get("stage", "")

            if event_type == "change_found":
                # Stream individual change to frontend
                yield f"event: change_found\ndata: {json.dumps(event.get('change', {}))}\n\n"
            elif stage == "complete":
                yield f"event: complete\ndata: {json.dumps(event)}\n\n"
                break
            elif stage == "failed":
                yield f"event: failed\ndata: {json.dumps(event)}\n\n"
                break
            else:
                yield f"event: progress\ndata: {json.dumps(event)}\n\n"

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

    # Get page counts for PDF viewer
    old_pages = 0
    new_pages = 0
    try:
        old_pages = get_page_count(job["old_pdf_path"])
        new_pages = get_page_count(job["new_pdf_path"])
    except Exception:
        pass

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
        "old_pages": old_pages,
        "new_pages": new_pages,
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


# Page image cache: job_id -> {(which, page_num): png_bytes}
_page_cache: dict[str, dict] = {}


@app.get("/api/analyze/{job_id}/page/{which}/{page_num}")
async def serve_page_image(job_id: str, which: str, page_num: int):
    """Render a single PDF page as a PNG image for the viewer."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    job = jobs[job_id]
    result = job.get("result")

    if which == "old":
        # Use annotated PDF if available, otherwise original
        path = (result or {}).get("old_annotated_path") or job.get("old_pdf_path")
    elif which == "new":
        path = (result or {}).get("new_annotated_path") or job.get("new_pdf_path")
    else:
        raise HTTPException(400, "Invalid type. Use 'old' or 'new'.")

    if not path or not os.path.exists(path):
        raise HTTPException(404, "PDF not found")

    # Check cache
    cache_key = (which, page_num)
    if job_id not in _page_cache:
        _page_cache[job_id] = {}
    if cache_key in _page_cache[job_id]:
        png_bytes = _page_cache[job_id][cache_key]
    else:
        try:
            png_bytes = await asyncio.to_thread(render_page_image, path, page_num, 150)
            _page_cache[job_id][cache_key] = png_bytes
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, f"Failed to render page: {str(e)}")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(len(png_bytes)),
        },
    )
