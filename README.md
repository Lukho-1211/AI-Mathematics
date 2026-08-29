# AI Mathematics Textbook → Explanation Video Generator

Convert a **scanned mathematics textbook page** into a professional, narrated explanation video powered by an in-house **MathVizAI** architecture (LLM scene planning → Manim animation → FFmpeg assembly), with OpenAI for math OCR, reasoning, and TTS.

The uploaded scan is used for **OCR and review only** — it is **not** shown in the generated MP4. The video draws the mathematics (graphs, diagrams, number lines, algebra steps) with distinct colors per concept.

## Architecture

- **Frontend**: Next.js 14 + TypeScript + Tailwind + KaTeX
- **Backend**: FastAPI (Python 3.12)
- **Workers**: Celery + Redis
- **DB**: PostgreSQL
- **Storage**: MinIO (S3)
- **Visualization**: MathVizAIProvider (Manim Community Edition)
- **Rendering**: FFmpeg (1080p + 720p H.264/AAC)

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

Without this, upload/infra work, but OCR / lesson / TTS / MathViz codegen will fail with a clear error.

### 3. Start infrastructure + API + worker

```bash
docker compose up -d --build postgres redis minio minio-init api worker
```

The first worker/API build installs TeX Live + Manim and can take several minutes.

### 4. Start the frontend (host)

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 5. Acceptance test

1. Create a new video and upload a page containing:

   ```text
   Quadratic equations
   Solve: x² - 5x + 6 = 0
   ```

2. Click **Upload & Analyze**.
3. On the project page, review extracted LaTeX (fix any flagged items).
4. Click **Approve & continue**, then **Generate Explanation Video**.
5. Watch live progress (OCR → understanding → script → MathVizAI → narration → render).
6. Preview and **Download MP4**.

A sample page image can be generated with:

```bash
python scripts/make_sample_page.py
```

## API overview

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/projects` | Create project |
| POST | `/api/upload/{id}` | Upload page (crop/rotate) |
| POST | `/api/ocr/{id}` | Queue math OCR |
| POST | `/api/ocr/{id}/review` | Approve corrected expressions |
| POST | `/api/projects/{id}/generate` | Queue full video pipeline |
| GET | `/api/progress/{id}` | SSE progress stream |
| GET | `/api/video/{id}/download` | Download MP4 |

## MathVizAI integration note

MathVizAI has **no hosted public API**. This project implements the published architecture in-house as `MathVizAIProvider` behind a `MathVizProvider` interface (`backend/app/services/providers/mathviz_ai.py`), so the visualization backend can be swapped later without rewriting the app.

## Project storage layout

```text
projects/{project_id}/
  original/
  ocr/
  lesson/
  scenes/
  mathviz/
  audio/
  video/
  subtitles/
```

## Development

```bash
# API logs
docker compose logs -f api worker

# Local API (optional, against dockerized postgres/redis/minio)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## License

MIT — for educational use.
