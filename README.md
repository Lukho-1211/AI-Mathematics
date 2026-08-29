# MathViz — Textbook → Explanation Video

Upload **one or more scanned mathematics textbook pages** and generate a narrated explanation video. An in-house **MathVizAI** pipeline (LLM scene planning → Manim animation → FFmpeg assembly) draws the mathematics; OpenAI handles OCR, lesson reasoning, and TTS.

The uploaded scan is used for **OCR and review only** — it is **not** shown in the generated MP4. The video draws graphs, diagrams, number lines, and algebra steps with a distinct color per concept.

## What you get

- Dashboard of lessons with status, progress, thumbnails, and delete
- Multi-page upload (JPG, JPEG, PNG, WEBP, PDF) — up to **10 pages**, **25MB** each
- Per-page crop, rotate, and zoom before upload
- Voice: female / male, speed 0.5–1.5×, language **en / es / fr / de**
- Human OCR review (flagged expressions must be corrected — the system does not invent math)
- Live progress (SSE + polling): OCR → understanding → script → scenes → narration → MathViz → render
- Preview in the browser; download **1080p / 720p MP4**, **SRT / VTT**, and a **lesson.md** export

## Architecture

| Layer | Stack |
|--------|--------|
| Frontend | Next.js 14 + TypeScript + Tailwind + KaTeX |
| Backend | FastAPI (Python 3.12) |
| Workers | Celery + Redis |
| Database | PostgreSQL 16 |
| Storage | MinIO (S3) |
| Visualization | `MathVizAIProvider` (Manim Community Edition) |
| Rendering | FFmpeg (1080p + 720p H.264/AAC) |

```text
Browser (localhost:3000)
        │
        ▼
   FastAPI (localhost:8000)
        │
        ├── PostgreSQL
        ├── Redis ──► Celery worker (OCR, lesson, TTS, Manim, FFmpeg)
        └── MinIO   (projects/{id}/original, ocr, lesson, scenes, …)
```

## Quick start

### 1. Prerequisites

- Docker Desktop
- Node.js 20+
- An OpenAI API key

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set a **real** OpenAI key:

```env
OPENAI_API_KEY=sk-...
```

Without this, upload and infra work, but OCR / lesson / TTS / MathViz codegen fail with a clear error.

### 3. Start infrastructure + API + worker

```bash
docker compose up -d --build postgres redis minio minio-init api worker
```

On Windows (PowerShell) you can use:

```powershell
.\scripts\dev.ps1
```

The first worker/API build installs TeX Live + Manim and can take several minutes.

When healthy:

- API: [http://localhost:8000/health](http://localhost:8000/health)
- MinIO console: [http://localhost:9001](http://localhost:9001) (`minioadmin` / `minioadmin`)

### 4. Start the frontend (host)

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

To run the frontend in Docker as well:

```bash
docker compose --profile full up -d --build web
```

### 5. Acceptance test

1. Generate a sample page (optional):

   ```bash
   python scripts/make_sample_page.py
   ```

   Output: `sample_data/quadratic_page.png`

2. In the app, click **New Video** and upload a page containing:

   ```text
   Quadratic equations
   Solve: x² - 5x + 6 = 0
   ```

3. Click **Upload & Analyze** (or **Upload only**, then **Analyze Page** on the project).
4. Review extracted LaTeX. Fix any items flagged for low confidence.
5. Click **Approve & continue**, then **Generate Explanation Video**.
6. Watch live progress, then preview and **Download MP4**.

## How a lesson is generated

1. **Upload** — files are validated, PDFs rasterized, crop/rotate applied, stored in MinIO.
2. **OCR** — vision model extracts expressions with confidence scores.
3. **Review** — you correct flagged items; generation is blocked until approval.
4. **Understanding** — topic, objectives, and teaching sequence.
5. **Script + scenes** — narration and visualization specs (graphs, number lines, geometry, algebra).
6. **Voice** — OpenAI TTS per scene.
7. **MathVizAI** — Manim renders each scene (retries on compile failure).
8. **Render** — FFmpeg assembles video + audio; optional SRT/VTT; quality checks.
9. **Finalize** — 1080p (primary) and 720p assets, lesson markdown.

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create project |
| GET | `/api/projects/{id}` | Project detail |
| PATCH | `/api/projects/{id}` | Update title / voice / language |
| DELETE | `/api/projects/{id}` | Delete project and stored files |
| POST | `/api/upload/{id}` | Upload a page (crop / rotate / PDF page / append) |
| POST | `/api/ocr/{id}` | Queue math OCR |
| GET | `/api/ocr/{id}/expressions` | List extracted expressions |
| PATCH | `/api/ocr/{id}/expressions/{expr}` | Correct one expression |
| POST | `/api/ocr/{id}/review` | Approve corrected expressions |
| POST | `/api/projects/{id}/generate` | Queue full video pipeline |
| GET | `/api/progress/{id}` | SSE progress stream |
| GET | `/api/video/{id}` | Redirect to primary MP4 |
| GET | `/api/video/{id}/download` | Download MP4 (`?resolution=1080p\|720p`) |
| GET | `/api/video/{id}/subtitles/{srt\|vtt}` | Download subtitles |
| GET | `/api/video/{id}/lesson` | Download `lesson.md` |

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs).

## MathVizAI integration note

MathVizAI has **no hosted public API**. This project implements the published architecture in-house as `MathVizAIProvider` behind a `MathVizProvider` interface (`backend/app/services/providers/mathviz_ai.py`), so the visualization backend can be swapped later without rewriting the app.

## Project storage layout

```text
projects/{project_id}/
  original/     # uploaded + processed page images
  ocr/
  lesson/       # lesson.md
  scenes/
  mathviz/      # per-scene Manim clips
  audio/
  video/        # 1080p + 720p MP4
  subtitles/    # SRT + VTT
```

## Development

```bash
# API + worker logs
docker compose logs -f api worker

# Local API (optional, against dockerized postgres/redis/minio)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Offline checks (no Docker / OpenAI required)
set PYTHONPATH=backend
python scripts/offline_acceptance.py

# Backend unit tests
cd backend
pytest

# API smoke (running stack + OPENAI_API_KEY)
python scripts/make_sample_page.py
python scripts/e2e_api_smoke.py
```

On PowerShell, set the path with `$env:PYTHONPATH='backend'` before the offline script.

## License

MIT — for educational use.
