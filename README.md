---
title: PaperToPpt
emoji: 📊
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# PaperToPpt

Upload a research-paper PDF and download an editable PowerPoint presentation.
The application extracts text, figures, and tables with PyMuPDF, asks Groq to
plan and summarize slides, then produces a `.pptx` with `python-pptx`.

## Deployment architecture

```
Browser
  │  same-origin HTTP on port 7860
  ▼
FastAPI ── serves compiled React/Vite SPA
  │
  ├── POST /upload → in-process background pipeline → /tmp/papertoppt
  ├── GET  /status/{job_id}
  └── GET  /download/{job_id}
          │
          ├── Groq API (HTTPS)
          └── generated .pptx download
```

The React application and API deliberately use one public port. This avoids
CORS and `localhost` problems in a Docker container and complies with a
Hugging Face Docker Space's single exposed `app_port`.

## Execution workflow and deployment changes

`backend/app.py` is the service entry point. An upload starts the background
pipeline in this order: `parser` → `section_detector` → `summarizer` →
`slide_planner` → `ppt_generator`. The browser polls status until the output is
available for download.

The original pipeline was structurally complete, but it was not deployable as
one application: Python dependencies were undeclared, Docker configuration was
absent, output paths were tied to the checkout, and the frontend called
`localhost:8000`. This revision adds a pinned dependency lock, a multi-stage
Docker image, Hugging Face Space metadata, environment-based runtime paths, and
same-origin API calls. It retains the existing extraction, planning, and PPTX
generation modules rather than rewriting them.

## Repository map

| Path | Purpose |
| --- | --- |
| `backend/app.py` | FastAPI endpoints, upload validation, job status, and background pipeline. |
| `backend/config.py` | Environment-based paths, CORS settings, and upload limit. |
| `backend/parser.py` | Extracts PDF text, images, figure captions, and tables. |
| `backend/section_detector.py` | Splits the paper into recognized academic sections. |
| `backend/summarizer.py` | Calls Groq for summaries and an intelligent slide plan. |
| `backend/slide_planner.py` | Normalizes the AI plan and provides a heuristic fallback. |
| `backend/ppt_generator.py` | Renders the selected theme as a PowerPoint file. |
| `frontend/src/App.jsx` | Upload, theme selection, job polling, and download UI. |
| `frontend/vite.config.js` | Local-development proxy from `/api` to FastAPI. |
| `Dockerfile` | Multi-stage frontend build and production FastAPI runtime. |
| `requirements.txt` | Pinned Python production dependencies. |

## Prerequisites

- Python 3.12 for the documented local setup
- Node.js 24 and npm for the frontend build
- Docker Desktop (or another Docker Engine) for container testing
- A Groq API key with access to the configured models

No GPU is required: all AI inference is performed by Groq over HTTPS. CPU Basic
hardware is the appropriate starting point for a Hugging Face Space.

## Configure the application

Never commit an API key. Copy the example and set a real key:

```powershell
Copy-Item backend/.env.example backend/.env
# Edit backend/.env and set GROQ_API_KEY
```

Environment settings are listed below. Hugging Face Space settings should hold
the secret rather than a `.env` file.

| Setting | Required | Default | Meaning |
| --- | --- | --- | --- |
| `GROQ_API_KEY` | Yes for conversion | none | Groq API key. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Primary Groq model. |
| `GROQ_FALLBACK_MODEL` | No | `openai/gpt-oss-20b` | Used after a rate-limit response. |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Maximum accepted PDF size. |
| `DATA_DIR` | No | `./data` locally, `/tmp/papertoppt` in Docker | Temporary upload/output parent directory. |
| `CORS_ORIGINS` | No | Vite localhost origins | Comma-separated origins for split local development only. |

## Run locally without Docker

From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The Vite development proxy sends `/api/*` to
FastAPI on port 8000. If PowerShell blocks `npm.ps1` under your execution
policy, use `npm.cmd ci` and `npm.cmd run dev` instead.

Check the backend independently:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

## Build and run the container

The Dockerfile has two stages. The first runs `npm ci` and `npm run build`, so
Node is excluded from the final image. The second installs the pinned Python
packages, copies only the backend and compiled frontend, creates UID 1000 for
Hugging Face compatibility, and starts one Uvicorn worker on port 7860.

```powershell
docker build --tag paper-to-ppt:local .
docker run --rm --name paper-to-ppt `
  --env-file backend/.env `
  --publish 7860:7860 `
  paper-to-ppt:local
```

Visit `http://localhost:7860`; the frontend is served by FastAPI. Verify health
and inspect the running container from another terminal:

```powershell
Invoke-RestMethod http://localhost:7860/healthz
docker logs --follow paper-to-ppt
docker exec -it paper-to-ppt sh
```

An API smoke test (replace the PDF path) is:

```powershell
curl.exe --fail-with-body -F "file=@.\paper.pdf;type=application/pdf" -F "theme=dark" http://localhost:7860/upload
```

Use its `job_id` with `http://localhost:7860/status/<job_id>` until status is
`done`, then download from `/download/<job_id>`. A real conversion requires a
valid Groq key and a representative PDF; the health endpoint does not.

## Deploy automatically from GitHub to Hugging Face Spaces

The committed workflow in `.github/workflows/deploy-huggingface.yml` deploys
every push to `main` (and can also be run manually from the Actions tab). It
uses Hugging Face's official `huggingface/hub-sync` action to mirror this
repository to a Docker Space; each mirrored commit triggers the Space rebuild.

Complete this one-time configuration before the first push:

1. The default target is `Deep712sharma/P2P`. To deploy to a differently named
   Space, add the optional GitHub Actions variable `HF_SPACE_ID` in
   **Settings → Secrets and variables → Actions → Variables**, using the exact
   `<HF_NAMESPACE>/<SPACE_NAME>` identifier. Create the Space first if you want
   to choose its visibility and hardware; otherwise the sync action creates a
   Docker Space on its first successful run.
2. Create a Hugging Face **fine-grained write token** scoped only to that Space.
   In GitHub **Actions secrets**, save it as `HF_TOKEN`. It is deliberately a
   secret, never a repository variable or checked-in file.
3. In the target Space's **Settings → Variables and secrets**, add
   `GROQ_API_KEY` as a Hugging Face **Secret**. Add non-sensitive optional
   settings such as `MAX_UPLOAD_SIZE_MB` as variables. Do not commit
   `backend/.env`.
4. Commit and push all deployment files to `main`. In GitHub Actions, the
   **Deploy to Hugging Face Space** run should complete, then the Space Logs
   should progress from build to `Running`. Verify `/healthz` and one small PDF
   conversion.

The workflow excludes `uploads/`, `outputs/`, and `data/`, so temporary user
PDFs and generated PowerPoints are not published to the Space. GitHub pushes
to other branches do not deploy.

The official Docker Space documentation confirms the `sdk: docker` metadata,
`app_port`, UID 1000 permissions model, runtime secrets, and ephemeral storage
behavior: [Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker).
The platform's account, hardware, secret, networking, and lifecycle details are
documented in the [Spaces overview](https://huggingface.co/docs/hub/spaces-overview).

## Operational notes and troubleshooting

| Symptom | Likely cause and smallest fix |
| --- | --- |
| Space build fails during `npm ci` | Ensure `frontend/package-lock.json` and `frontend/package.json` are committed together. Rebuild after updating the lockfile locally. |
| App is unreachable in a Space | Confirm the README has `app_port: 7860` and the image starts Uvicorn on 7860. Do not expose Vite separately. |
| Upload returns 503 | Add `GROQ_API_KEY` as a Space Secret or pass `--env-file backend/.env` locally, then restart. |
| Upload returns 413 | Reduce PDF size or increase `MAX_UPLOAD_SIZE_MB` deliberately after considering memory and disk usage. |
| Browser calls `localhost:8000` | Rebuild the frontend. Production uses same-origin URLs; Vite's `/api` proxy is development-only. |
| Job shows “Processing failed” | Read `docker logs paper-to-ppt` or the Space Runtime logs; Groq authentication/model access and malformed PDFs are the first checks. |
| A job disappears after restart | Expected: job state and temporary files are in process/ephemeral storage. Download files before restart. Add shared state and persistent storage before treating this as a multi-user durable service. |
| Downloads fail only on a multi-worker deployment | Keep one Uvicorn worker. The current in-memory job dictionary is not shared between workers. |

For production hardening, retain the current file-size and filename validation,
keep secrets out of Git and logs, restrict `CORS_ORIGINS` if the API is ever
split from the UI, and monitor Groq usage/rate limits. If you need concurrent,
durable jobs, the next architectural change should be a task queue plus a shared
status store and object storage—not more Uvicorn workers. Hugging Face Docker
Space disk is ephemeral; attach a storage solution only when persisting user
files is an explicit product requirement.
