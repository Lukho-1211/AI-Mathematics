# MathViz — Textbook → Explanation Video

Upload **one or more scanned mathematics textbook pages** and generate a narrated explanation video. An in-house **MathVizAI** pipeline (LLM scene planning → Manim animation → FFmpeg assembly) draws the mathematics; OpenAI handles OCR, lesson reasoning, and TTS.

The uploaded scan is used for **OCR and review only** — it is **not** shown in the generated MP4. The video draws graphs, diagrams, number lines, and algebra steps with a distinct color per concept (gold / blue / green / rose / violet).

There is **no login**. A demo user (`demo@mathviz.local`) is created on API startup.

## What you get

- Dashboard of lessons with status, progress, thumbnails, and delete
- Multi-page upload (JPG, JPEG, PNG, WEBP, PDF) — up to **10 pages**, **25MB** each
- Drag-and-drop, page reorder, per-page crop / rotate / zoom, PDF page picker
- Voice: female / male, speed 0.5–1.5×, language **en / es / fr / de**
- Human OCR review (flagged expressions must be corrected — the system does not invent math)
- Live progress (SSE + polling): OCR → understanding → script → scenes → narration → MathViz → render
- In-browser preview; download **1080p / 720p MP4**, **SRT / VTT**, and a **lesson.md** export
- SymPy algebra-step check before render; FFmpeg probe (video + audio + duration) after mux

## Architecture

| Layer | Stack |
|--------|--------|
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind + KaTeX |
| Backend | FastAPI (Python 3.12) |
| Workers | Celery + Redis 7 (`concurrency=1`) |
| Database | PostgreSQL 16 (SQLAlchemy; `create_all` on boot, Alembic available) |
| Storage | MinIO (S3-compatible) |
| Visualization | `MathVizAIProvider` (Manim Community Edition 0.18) |
| Rendering | FFmpeg (1080p H.264/AAC CRF 20, plus 720p transcode) |

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

### Repository layout

```text
frontend/     Next.js app (dashboard, create, project review)
backend/      FastAPI + Celery + services
docker/       Dockerfiles for API/worker and frontend
scripts/      PowerShell helper, sample page, smoke tests
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

PowerShell:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set a **real** OpenAI key:

```env
OPENAI_API_KEY=sk-...
```

Without this, upload and infra work, but OCR / lesson / TTS / MathViz codegen fail with a clear error. After changing `.env`, restart `api` and `worker`.

Docker Compose overrides hostnames for services running in containers (`postgres`, `redis`, `minio`). The defaults in `.env.example` already match that. If you run the API **on the host** against Dockerized infra, use `localhost` for Postgres, Redis, and MinIO instead.

### 3. Start infrastructure + API + worker

```bash
docker compose up -d --build postgres redis minio minio-init api worker
```

On Windows (PowerShell):

```powershell
.\scripts\dev.ps1
```

The first worker/API build installs TeX Live + Manim and can take several minutes.

The worker sets `MANIM_QUALITY=low` for faster local scene renders. Set `MANIM_QUALITY=high` on the worker if you want production-quality Manim (much slower).

When healthy:

- API: [http://localhost:8000/health](http://localhost:8000/health)
- OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs)
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
4. Review extracted LaTeX. Fix any items flagged for low confidence (default threshold **0.75**).
5. Click **Approve & continue**, then **Generate Explanation Video**.
6. Watch live progress, then preview and **Download MP4**.

## How a lesson is generated

1. **Upload** — files are validated by magic bytes, PDFs rasterized at 200 DPI, crop/rotate applied, stored in MinIO. The first file in a batch replaces existing pages; later files append.
2. **OCR** — vision model extracts expressions with confidence scores. Items below the threshold are flagged `needs_review`.
3. **Review** — you correct flagged items; generation is blocked until approval.
4. **Understanding** — topic, objectives, and teaching sequence.
5. **Script + scenes** — narration and visualization specs (graphs, number lines, geometry, algebra). Leftover `textbook_page` specs are remapped so the scan never appears in the video.
6. **Math QC** — SymPy checks algebra-step scenes (roots must satisfy the original equation).
7. **Voice** — OpenAI TTS per scene (`nova` female / `onyx` male by default).
8. **MathVizAI** — Manim renders each scene (up to 3 compile retries, 180s timeout). On codegen failure, a title/equation fallback scene is used.
9. **Render** — FFmpeg muxes video + audio, concatenates scenes, transcodes 720p; probe requires video + audio streams and ≥ 3s duration.
10. **Finalize** — SRT/VTT + `lesson.md`.

## Environment variables

Copy from [`.env.example`](.env.example). Only `OPENAI_API_KEY` must be changed for a local Docker run.

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for OCR, lesson/script/scene planning, TTS, Manim codegen |
| `OPENAI_VISION_MODEL` | OCR (default `gpt-4o`) |
| `OPENAI_REASONING_MODEL` | Lesson / script / scene planning (default `gpt-4o`) |
| `OPENAI_TTS_MODEL` | TTS (default `tts-1`) |
| `OPENAI_TTS_VOICE_MALE` / `_FEMALE` | TTS voices (`onyx` / `nova`) |
| `DATABASE_URL` | Postgres (`…@postgres:5432/mathviz` in Docker) |
| `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis / Celery |
| `S3_ENDPOINT_URL` / `S3_*` | MinIO bucket `mathviz` |
| `S3_PUBLIC_URL` | Browser-facing object URLs (`http://127.0.0.1:9000`) |
| `API_CORS_ORIGINS` | Frontend origin (`http://localhost:3000`) |
| `NEXT_PUBLIC_API_URL` | Frontend → API (`http://localhost:8000`) |
| `MAX_UPLOAD_MB` | Per-file upload limit (default `25`) |
| `OCR_CONFIDENCE_THRESHOLD` | Flag for human review (default `0.75`) |
| `MANIM_MAX_ATTEMPTS` / `MANIM_TIMEOUT_SEC` | Scene compile retries / timeout |
| `DEFAULT_USER_EMAIL` | Auto-created demo account |

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create project |
| GET | `/api/projects/{id}` | Project detail |
| PATCH | `/api/projects/{id}` | Update title / voice / language / subtitles |
| DELETE | `/api/projects/{id}` | Delete project and stored files |
| POST | `/api/upload/{id}` | Upload a page (`crop_json`, `rotation`, `page_number`, `replace`) |
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

Drawn scene kinds: **graph_2d**, **number_line**, **geometry**, **algebra_steps**. Title/summary cards stay text-only. Manim never uses `ImageMobject` or the uploaded page.

## Project storage layout

```text
projects/{project_id}/
  original/     # uploaded + processed page images
  ocr/
  lesson/       # lesson.md
  scenes/       # scenes.json
  mathviz/      # per-scene Manim clips + generated .py
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

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Frontend: “Cannot reach the API” | `docker compose up -d postgres redis minio minio-init api worker` then `GET /health` |
| OCR / TTS / codegen errors mentioning API key | Real `OPENAI_API_KEY` in `.env`; restart `api` and `worker` |
| First `docker compose` build is slow | Expected — TeX Live + Manim in `docker/Dockerfile.backend` |
| Manim scenes look low-res locally | Worker uses `MANIM_QUALITY=low`; set `high` for final quality |
| Generation blocked after OCR | Correct every `needs_review` expression, then **Approve & continue** |
| Invalid upload (`.txt`, empty, oversized) | Magic-byte check; JPG/PNG/WEBP/PDF only; max 25MB |

## License

MIT — for educational use.
