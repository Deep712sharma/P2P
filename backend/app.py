"""
app.py – FastAPI server for the PaperToPpt pipeline.
"""

import os
import sys
import uuid
import shutil
import logging
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Add backend directory to path so relative imports work ───────────────────
sys.path.insert(0, os.path.dirname(__file__))

from parser import extract_pdf
from section_detector import detect_sections
from summarizer import summarize_all_sections
from slide_planner import build_slide_plan
from ppt_generator import generate_pptx
from config import settings

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

UPLOAD_DIR = settings.upload_dir
OUTPUT_DIR = settings.output_dir
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
VALID_THEMES = {"dark", "light", "nature", "sunset"}

app = FastAPI(
    title="PaperToPpt API",
    description="Convert research paper PDFs to PowerPoint presentations using AI.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job status store  {job_id: {status, message, pptx_path}}
jobs: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Background pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(job_id: str, pdf_path: str, theme: str = "dark"):
    """Full PDF → PPTX pipeline executed in a background task."""
    try:
        jobs[job_id]["status"]  = "processing"
        jobs[job_id]["message"] = "Extracting text and images from PDF…"

        # 1. Parse PDF
        img_dir = str(UPLOAD_DIR / job_id / "images")
        extracted = extract_pdf(pdf_path, img_output_dir=img_dir)

        jobs[job_id]["message"] = "Detecting sections…"

        # 2. Detect sections
        sections = detect_sections(extracted["full_text"])

        jobs[job_id]["message"] = "Summarizing sections with AI…"

        # 3. Summarize
        summarized = summarize_all_sections(
            sections=sections,
            title=extracted["title"],
            authors=extracted["authors"],
            abstract=extracted["abstract"],
        )

        jobs[job_id]["message"] = "Planning slide structure with AI…"

        # 4. Plan slides (pass tables + captions for smart LLM placement)
        slide_plan = build_slide_plan(
            title=extracted["title"],
            authors=extracted["authors"],
            summarized=summarized,
            sections=sections,
            images=extracted["images"],
            tables=extracted.get("tables", []),
            figure_captions=extracted.get("figure_captions", []),
            table_captions=extracted.get("table_captions", []),
        )

        jobs[job_id]["message"] = "Generating PowerPoint file…"

        # 5. Generate PPTX
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in extracted["title"])[:40]
        output_filename = f"{safe_title}_{job_id[:8]}.pptx"
        output_path = str(OUTPUT_DIR / output_filename)
        generate_pptx(slide_plan, output_path, theme_name=theme)

        jobs[job_id]["status"]      = "done"
        jobs[job_id]["message"]     = "Presentation ready!"
        jobs[job_id]["pptx_path"]   = output_path
        jobs[job_id]["filename"]    = output_filename
        jobs[job_id]["slide_count"] = len(slide_plan)
        jobs[job_id]["title"]       = extracted["title"]

    except Exception:
        logger.exception("Pipeline failed for job %s", job_id)
        jobs[job_id]["status"]  = "error"
        jobs[job_id]["message"] = "Processing failed. Check the server logs for details."


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def health():
    """Unauthenticated health endpoint for local and platform checks."""
    return {"status": "ok", "service": "PaperToPpt API v1.0"}


@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    theme: str = Form("dark"),
):
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    if theme not in VALID_THEMES:
        raise HTTPException(status_code=400, detail="Unsupported presentation theme.")
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY is not configured on the server.",
        )

    job_id   = str(uuid.uuid4())
    job_dir  = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = job_dir / filename

    # Stream to disk so clients cannot bypass the advertised upload-size limit.
    bytes_written = 0
    try:
        with pdf_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"PDF exceeds the {settings.max_upload_size_mb} MB upload limit."
                        ),
                    )
                destination.write(chunk)
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    # Init job record
    jobs[job_id] = {
        "status":  "queued",
        "message": "Queued for processing…",
        "pptx_path": None,
        "filename": None,
    }

    # Start pipeline in background
    background_tasks.add_task(_run_pipeline, job_id, str(pdf_path), theme)

    return JSONResponse({"job_id": job_id, "message": "Upload successful. Processing started."})


@app.get("/status/{job_id}")
def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = jobs[job_id]
    return {
        "job_id":      job_id,
        "status":      job["status"],
        "message":     job["message"],
        "slide_count": job.get("slide_count"),
        "title":       job.get("title"),
        "filename":    job.get("filename"),
    }


@app.get("/download/{job_id}")
def download_pptx(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="Presentation not ready yet.")
    pptx_path = job["pptx_path"]
    if not pptx_path or not os.path.exists(pptx_path):
        raise HTTPException(status_code=404, detail="Output file missing.")
    return FileResponse(
        path=pptx_path,
        filename=job["filename"],
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


# The Docker image supplies this directory after compiling the Vite frontend.
# Keeping the mount optional preserves the existing two-process Vite workflow
# for local development without requiring a pre-built frontend.
if settings.frontend_dist_dir.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=settings.frontend_dist_dir, html=True),
        name="frontend",
    )
