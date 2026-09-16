import { useState, useCallback, useRef } from 'react'
import './App.css'

const API = 'http://localhost:8000'

// ── Step icons ─────────────────────────────────────────────────────────────
const STEPS = [
  { id: 'upload',   label: 'Upload PDF',         icon: '📄' },
  { id: 'extract',  label: 'Extract Content',     icon: '🔍' },
  { id: 'detect',   label: 'Detect Sections',     icon: '📑' },
  { id: 'summarize',label: 'AI Summarization',    icon: '🤖' },
  { id: 'plan',     label: 'Plan Slides',         icon: '🗂️' },
  { id: 'generate', label: 'Generate PPTX',       icon: '✨' },
]

function ProgressSteps({ status }) {
  const activeIndex = {
    queued:     0,
    processing: 2,
    done:       5,
    error:      -1,
  }[status] ?? 0

  return (
    <div className="progress-steps">
      {STEPS.map((step, i) => {
        const done    = i < activeIndex
        const active  = i === activeIndex
        const cls     = done ? 'step done' : active ? 'step active' : 'step'
        return (
          <div key={step.id} className={cls}>
            <div className="step-icon">
              {done ? '✓' : step.icon}
            </div>
            <span className="step-label">{step.label}</span>
            {i < STEPS.length - 1 && <div className={`step-connector ${done ? 'filled' : ''}`} />}
          </div>
        )
      })}
    </div>
  )
}

function DropZone({ onFile, disabled }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragging(false)
    if (disabled) return
    const file = e.dataTransfer.files[0]
    if (file?.type === 'application/pdf') onFile(file)
  }, [onFile, disabled])

  const handleChange = (e) => {
    const file = e.target.files[0]
    if (file) onFile(file)
  }

  return (
    <div
      id="drop-zone"
      className={`dropzone ${dragging ? 'dragging' : ''} ${disabled ? 'disabled' : ''}`}
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        id="pdf-file-input"
        type="file"
        accept=".pdf"
        style={{ display: 'none' }}
        onChange={handleChange}
      />
      <div className="dropzone-inner animate-float">
        <div className="dropzone-icon">📄</div>
        <div className="dropzone-text">
          <p className="dropzone-headline">Drop your research paper here</p>
          <p className="dropzone-sub">or <span className="link">click to browse</span> — PDF only</p>
        </div>
        <div className="dropzone-badge">Up to 50 MB</div>
      </div>
    </div>
  )
}

function ProgressBar({ pct }) {
  return (
    <div className="pbar-wrap">
      <div className="pbar-track">
        <div className="pbar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="pbar-pct">{pct}%</span>
    </div>
  )
}

function StatusCard({ job, jobId }) {
  const isProcessing = job?.status === 'processing' || job?.status === 'queued'
  const isDone       = job?.status === 'done'
  const isError      = job?.status === 'error'

  const pct = {
    queued:     10,
    processing: 65,
    done:       100,
    error:      0,
  }[job?.status] ?? 0

  return (
    <div className={`status-card glass animate-fade-up ${isDone ? 'done' : ''} ${isError ? 'error' : ''}`}>
      <ProgressSteps status={job?.status} />
      <div className="status-msg">
        {isProcessing && (
          <div className="spinner-row">
            <div className="spinner" />
            <span>{job?.message}</span>
          </div>
        )}
        {isDone && (
          <div className="done-row">
            <span className="done-icon">🎉</span>
            <div>
              <p className="done-title">{job?.title || 'Presentation Ready!'}</p>
              <p className="done-sub">{job?.slide_count} slides generated</p>
            </div>
          </div>
        )}
        {isError && (
          <div className="error-row">
            <span>❌</span>
            <span>{job?.message}</span>
          </div>
        )}
      </div>
      {isProcessing && <ProgressBar pct={pct} />}
      {isDone && (
        <a
          id="download-btn"
          href={`${API}/download/${jobId}`}
          className="btn btn-success"
          download
        >
          ⬇ Download PPTX
        </a>
      )}
    </div>
  )
}

export default function App() {
  const [file,   setFile]   = useState(null)
  const [jobId,  setJobId]  = useState(null)
  const [job,    setJob]    = useState(null)
  const [error,  setError]  = useState('')
  const [uploading, setUploading] = useState(false)
  const [theme, setTheme] = useState('dark')
  const pollRef = useRef(null)

  const THEMES = [
    { id: 'dark', label: 'Neon', bg: '#0D112B', accent: '#00D4FF' },
    { id: 'light', label: 'Academic', bg: '#F8FAFC', accent: '#0066CC', border: '#CBD5E0' },
    { id: 'nature', label: 'Forest', bg: '#0A1F15', accent: '#DFB75D' },
    { id: 'sunset', label: 'Sunset', bg: '#2B0E18', accent: '#FF7E67' },
  ]

  const handleFile = (f) => {
    setFile(f)
    setJob(null)
    setJobId(null)
    setError('')
  }

  const poll = (id) => {
    pollRef.current = setInterval(async () => {
      try {
        const res  = await fetch(`${API}/status/${id}`)
        const data = await res.json()
        setJob(data)
        if (data.status === 'done' || data.status === 'error') {
          clearInterval(pollRef.current)
        }
      } catch {
        // ignore transient errors
      }
    }, 1500)
  }

  const handleUpload = async () => {
    if (!file) return
    setError('')
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('theme', theme)
      const res  = await fetch(`${API}/upload`, { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')
      setJobId(data.job_id)
      setJob({ status: 'queued', message: 'Queued for processing…' })
      poll(data.job_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  const handleReset = () => {
    clearInterval(pollRef.current)
    setFile(null); setJobId(null); setJob(null); setError('')
  }

  const processing = job && (job.status === 'queued' || job.status === 'processing')

  return (
    <div className="app-shell">
      {/* ── Navbar ── */}
      <header className="navbar glass">
        <div className="navbar-inner">
          <div className="brand">
            <span className="brand-icon">📊</span>
            <span className="brand-name gradient-text">PaperToPpt</span>
          </div>
          <nav className="nav-links">
            <a href="#how-it-works">How it works</a>
            <a href="https://github.com" className="btn btn-outline" style={{ padding: '8px 18px', fontSize: 13 }}>
              GitHub
            </a>
          </nav>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="hero">
        <div className="hero-content">
          <div className="hero-badge animate-fade-in">✨ Powered by GPT-4o</div>
          <h1 className="hero-title animate-fade-up">
            Research Paper<br />
            <span className="gradient-text">→ Presentation</span>
          </h1>
          <p className="hero-sub animate-fade-up" style={{ animationDelay: '0.1s' }}>
            Upload any PDF and get a clean, editable PowerPoint in under a minute.<br />
            No manual slide-making. No copy-pasting. Just AI-powered results.
          </p>
        </div>
      </section>

      {/* ── Upload card ── */}
      <main className="main-card-wrap">
        <div className="upload-card glass animate-fade-up" style={{ animationDelay: '0.2s' }}>

          {!job ? (
            <>
              <DropZone onFile={handleFile} disabled={uploading} />
              {file && (
                <div className="file-pill animate-fade-in">
                  <span className="file-pill-icon">📄</span>
                  <span className="file-pill-name">{file.name}</span>
                  <span className="file-pill-size">{(file.size / 1024 / 1024).toFixed(2)} MB</span>
                  <button id="remove-file-btn" className="file-pill-remove" onClick={handleReset}>✕</button>
                </div>
              )}
              {error && <div className="error-banner animate-fade-in">⚠ {error}</div>}
              
              {file && (
                <div className="theme-selector animate-fade-in" style={{ marginBottom: 24 }}>
                  <label style={{ color: 'var(--text-dim)', fontSize: 13, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12, display: 'block', textAlign: 'center' }}>Choose Presentation Template</label>
                  <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
                    {THEMES.map(t => (
                      <button
                        key={t.id}
                        onClick={() => setTheme(t.id)}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          gap: 8,
                          padding: '12px 16px',
                          background: 'rgba(255,255,255,0.03)',
                          border: theme === t.id ? `2px solid ${t.accent}` : '2px solid transparent',
                          borderRadius: 12,
                          cursor: 'pointer',
                          transition: 'all 0.2s',
                          opacity: theme === t.id ? 1 : 0.6,
                        }}
                      >
                        <div style={{
                          width: 48, height: 32, borderRadius: 6, background: t.bg,
                          border: t.border ? `1px solid ${t.border}` : 'none',
                          boxShadow: `0 0 0 2px ${t.bg}, 0 0 0 4px ${t.accent}`,
                          transform: 'scale(0.8)'
                        }} />
                        <span style={{ color: theme === t.id ? 'white' : 'var(--text-dim)', fontSize: 13, fontWeight: theme === t.id ? '600' : '400' }}>
                          {t.label}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button
                id="generate-btn"
                className="btn btn-primary full-width"
                disabled={!file || uploading}
                onClick={handleUpload}
              >
                {uploading ? (
                  <><div className="spinner-sm" /> Uploading…</>
                ) : (
                  <>🚀 Generate Presentation</>
                )}
              </button>
            </>
          ) : (
            <>
              <StatusCard job={job} jobId={jobId} />
              {!processing && (
                <button id="start-over-btn" className="btn btn-outline full-width" onClick={handleReset} style={{ marginTop: 16 }}>
                  ↩ Start Over
                </button>
              )}
            </>
          )}
        </div>
      </main>

      {/* ── How it works ── */}
      <section className="how-section" id="how-it-works">
        <h2 className="section-title">How It Works</h2>
        <div className="how-grid">
          {[
            { icon: '📤', step: '01', title: 'Upload PDF',          desc: 'Drag and drop your research paper — any arXiv, IEEE, or ACM format.' },
            { icon: '🤖', step: '02', title: 'AI Processes It',      desc: 'GPT-4o reads every section: abstract, methods, results, and more.' },
            { icon: '🗂️', step: '03', title: 'Slides Are Planned',  desc: 'Logical slide order is auto-generated with concise bullet points.' },
            { icon: '⬇', step: '04', title: 'Download & Edit',      desc: 'Get a polished .pptx you can fully customize in PowerPoint or Google Slides.' },
          ].map((item) => (
            <div key={item.step} className="how-card glass-light">
              <div className="how-step-num">{item.step}</div>
              <div className="how-icon">{item.icon}</div>
              <h3>{item.title}</h3>
              <p>{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="footer">
        <p>Built with FastAPI · PyMuPDF · python-pptx · GPT-4o</p>
      </footer>
    </div>
  )
}
