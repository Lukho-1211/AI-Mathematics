"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import projects_router, upload_ocr_router, video_progress_router
from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.logging import setup_logging
from app.models import User
from app.services.storage import get_storage


def _ensure_job_stage_enum() -> None:
    """create_all will not add values to an existing Postgres enum."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_type WHERE typname = 'job_stage'
                    ) AND NOT EXISTS (
                        SELECT 1
                        FROM pg_enum e
                        JOIN pg_type t ON e.enumtypid = t.oid
                        WHERE t.typname = 'job_stage' AND e.enumlabel = 'SCENES'
                    ) THEN
                        ALTER TYPE job_stage ADD VALUE 'SCENES';
                    END IF;
                END
                $$;
                """
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    # Create tables (Alembic also available; create_all keeps MVP bootstrapping simple)
    Base.metadata.create_all(bind=engine)
    try:
        _ensure_job_stage_enum()
    except Exception:
        # Non-Postgres or permissions — ignore; Alembic migration covers production.
        pass
    settings = get_settings()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == settings.default_user_email).first()
        if not user:
            db.add(User(email=settings.default_user_email, display_name="Demo User"))
            db.commit()
    finally:
        db.close()
    # Ensure bucket exists
    try:
        get_storage()
    except Exception:
        pass
    yield


app = FastAPI(
    title="AI Mathematics Textbook Video Generator",
    description="Upload a scanned math textbook page and generate a MathVizAI explanation video.",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins + ["http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(upload_ocr_router)
app.include_router(video_progress_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
