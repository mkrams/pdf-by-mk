# PDF by MK

AI-powered document comparison tool that produces a verified change register between two PDF versions. Upload two PDFs and get a comprehensive, classified, and verified list of every change — with annotated PDFs, real-time progress, and an interactive viewer.

Built with Claude (Sonnet 4.5) as an agentic backend that autonomously extracts, diffs, classifies, verifies, and annotates changes.

![Stack](https://img.shields.io/badge/React-18-blue) ![Stack](https://img.shields.io/badge/FastAPI-0.115-green) ![Stack](https://img.shields.io/badge/Claude_API-Sonnet_4.5-orange)

---

## Features

- **Agentic analysis** — Claude autonomously runs a multi-step pipeline: extract text, detect structure, find revision history, diff sections, classify changes, verify NEW/REMOVED items, and assess impact
- **Revision history auto-detection** — scans the document for built-in change manifests and uses them as ground truth
- **Full-document verification** — NEW items are searched across the entire old document to confirm absence; REMOVED items are searched across the entire new document to confirm no traces remain
- **Two-layer PDF annotation** — paragraph-level background highlight + specific text highlight on both old and new PDFs
- **Interactive 3-panel viewer** — filterable change list (left), change detail with old/new comparison (center), PDF viewer (right)
- **Real-time progress** — Server-Sent Events stream the agent's progress as it works
- **Dark mode** — full dark mode support across the viewer
- **Keyboard navigation** — `j`/`k` to move between changes, `1`/`2` to switch PDF tabs

## Architecture

```
frontend/          React + TypeScript + Vite + TailwindCSS
  ├── UploadPage   Drag-and-drop PDF upload with labels
  └── ViewerPage   3-panel viewer (ChangeList, ChangeDetail, PdfViewer)

backend/           Python + FastAPI
  ├── pdf_utils    Text extraction, search, section parsing, diff, annotation
  ├── tools        8 Claude tool definitions + executor
  ├── agent        Claude agent orchestrator (up to 30 tool-calling turns)
  └── main         API endpoints (upload, SSE progress, results, PDF download)
```

## Prerequisites

- Python 3.10+
- Node.js 18+
- An [Anthropic API key](https://console.anthropic.com/)

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create .env from the example
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` and proxies `/api` requests to the backend at `http://localhost:8000`.

### Run Tests

```bash
cd backend
pip install pytest
python -m pytest tests/ -v
```

## Deployment

### Backend → Railway

1. Push this repo to GitHub
2. Go to [railway.com](https://railway.com) → **New Project** → **Deploy from GitHub Repo**
3. Set **Root Directory** to `backend`
4. Add environment variables:
   - `ANTHROPIC_API_KEY` — your API key
   - `CORS_ORIGINS` — your Vercel frontend URL (e.g. `https://pdf-compare.vercel.app`)
5. Deploy — Railway will build using the Dockerfile

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project** → import the same repo
2. Set **Root Directory** to `frontend`
3. Add environment variable:
   - `VITE_API_URL` — your Railway backend URL (e.g. `https://pdf-compare-production-xxxx.up.railway.app`)
4. Deploy — Vercel will run `npm run build` automatically

After both are deployed, update `CORS_ORIGINS` on Railway to match your actual Vercel URL.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/analyze` | Upload two PDFs, starts analysis job |
| `GET` | `/api/analyze/:id/progress` | SSE stream of analysis progress |
| `GET` | `/api/analyze/:id/result` | Full analysis result JSON |
| `GET` | `/api/analyze/:id/pdf/old` | Download annotated old PDF |
| `GET` | `/api/analyze/:id/pdf/new` | Download annotated new PDF |
| `GET` | `/api/health` | Health check |

## How It Works

1. **Upload** — Two PDFs are uploaded and saved server-side
2. **Agent loop** — Claude is given tools to extract text, detect structure, search, and diff. It runs autonomously for up to 30 turns.
3. **Verification** — The agent searches the full text of each document to verify that NEW items truly don't exist in the old version and REMOVED items truly don't appear in the new version.
4. **Annotation** — After the agent submits its change register, the backend generates annotated PDFs with two-layer highlighting.
5. **Viewer** — The frontend displays changes in a filterable, searchable 3-panel layout with embedded PDF viewing.

## License

MIT
