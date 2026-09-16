"""
app.py – FastAPI server for the PaperToPpt pipeline.
"""

import os
import sys
import uuid
import shutil
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

# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent.parent
UPLOAD_DIR  = BASE_DIR / "uploads"
OUTPUT_DIR  = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="PaperToPpt API",
    description="Convert research paper PDFs to PowerPoint presentations using AI.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

    except Exception as e:
        jobs[job_id]["status"]  = "error"
        jobs[job_id]["message"] = str(e)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "service": "PaperToPpt API v1.0"}


@app.post("/upload")
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    theme: str = Form("dark"),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    job_id   = str(uuid.uuid4())
    job_dir  = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(job_dir / file.filename)

    # Save uploaded file
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Init job record
    jobs[job_id] = {
        "status":  "queued",
        "message": "Queued for processing…",
        "pptx_path": None,
        "filename": None,
    }

    # Start pipeline in background
    background_tasks.add_task(_run_pipeline, job_id, pdf_path, theme)

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
