# PaperToPpt 📊

> **Upload a research paper PDF → Get a clean, editable PowerPoint in under a minute.**

Powered by PyMuPDF, Groq (llama-3.3-70b-versatile), python-pptx, and React + Vite.

---

## Project Structure

```
PaperToPpt/
├── backend/
│   ├── app.py              ← FastAPI server (upload, status, download)
│   ├── parser.py           ← PDF text + image extraction (PyMuPDF)
│   ├── section_detector.py ← Detect & split paper sections
│   ├── summarizer.py       ← Groq (Llama) section → bullet points
│   ├── slide_planner.py    ← Map sections to ordered slide plan
│   ├── ppt_generator.py    ← Build .pptx with python-pptx (dark theme)
│   └── .env                ← GROQ_API_KEY goes here
├── frontend/               ← Vite + React UI
│   └── src/
│       ├── App.jsx         ← Main UI (drag-drop, polling, download)
│       ├── App.css
│       └── index.css
├── uploads/                ← Temporary PDF storage (auto-created)
├── outputs/                ← Generated PPTX files (auto-created)
├── start_backend.bat       ← One-click backend start
└── start_frontend.bat      ← One-click frontend start
```

---

## ⚡ Quick Start

### 1. Set your Groq API key

Get your free key at https://console.groq.com, then edit `backend/.env`:
```
GROQ_API_KEY=gsk_your-groq-api-key-here
```

### 2. Start the backend (Terminal 1)

```powershell
cd d:\PaperToPpt
conda activate paper2ppt
cd backend
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 3. Start the frontend (Terminal 2)

```powershell
cd d:\PaperToPpt\frontend
conda run -n paper2ppt npm run dev
```

### 4. Open the app

Go to **http://localhost:5173** in your browser.

---

## 🔄 Pipeline

```
User uploads PDF
       │
       ▼
PyMuPDF extracts text + images
       │
       ▼
section_detector.py identifies sections
(Abstract, Intro, Methods, Results, Conclusion…)
       │
       ▼
Groq (llama-3.3-70b-versatile) summarizes each section → 4–6 bullet points
       │
       ▼
slide_planner.py builds an ordered slide plan
       │
       ▼
ppt_generator.py creates a themed .pptx
       │
       ▼
User downloads the file
```

---

## 🎨 Slide Theme

- Dark navy background (`#0D112B`)  
- Cyan accent (`#00D4FF`) + Purple accent (`#7C3AED`)  
- Slides: Title · Content (per section) · Key Figures · Thank You

---

## 📦 Conda Environment

The project uses a dedicated conda env `paper2ppt` (Python 3.11).  
All dependencies are installed inside it — nothing is installed globally.

To verify:
```powershell
conda run -n paper2ppt pip list
```
