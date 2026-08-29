"""Project CRUD and generation trigger endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    JobStage,
    JobStatus,
    GenerationJob,
    Project,
    ProjectStatus,
    User,
)
from app.schemas import (
    GenerateRequest,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    LessonPlanOut,
    ScriptOut,
    MathExpressionOut,
    SceneOut,
    JobOut,
    VideoAssetOut,
    SubtitleAssetOut,
)
from app.services.storage import get_storage
from app.core.config import get_settings

router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_or_create_default_user(db: Session) -> User:
    settings = get_settings()
    user = db.query(User).filter(User.email == settings.default_user_email).first()
    if user is None:
        user = User(email=settings.default_user_email, display_name="Demo User")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def serialize_project(db: Session, project: Project) -> ProjectDetail:
    storage = get_storage()
    uploaded_url = None
    if project.uploaded_files:
        key = project.uploaded_files[0].processed_storage_key or project.uploaded_files[0].storage_key
        uploaded_url = storage.presigned_url(key)

    videos = []
    for v in project.video_assets:
        videos.append(
            VideoAssetOut(
                id=v.id,
                resolution=v.resolution,
                duration_sec=v.duration_sec,
                url=storage.presigned_url(v.storage_key),
                is_primary=v.is_primary,
                validated=v.validated,
            )
        )
    subs = []
    for s in project.subtitle_assets:
        subs.append(
            SubtitleAssetOut(
                id=s.id,
                format=s.format,
                url=storage.presigned_url(s.storage_key),
            )
        )

    ocr_reviewed = bool(project.ocr_results and project.ocr_results[-1].reviewed)
    lesson = None
    if project.lesson_plan:
        lesson = LessonPlanOut.model_validate(project.lesson_plan)
    script = None
    if project.script:
        script = ScriptOut.model_validate(project.script)

    return ProjectDetail(
        id=project.id,
        title=project.title,
        status=project.status,
        progress_percent=project.progress_percent,
        progress_stage=project.progress_stage,
        error_message=project.error_message,
        voice_gender=project.voice_gender,
        voice_speed=project.voice_speed,
        language=project.language,
        accent=project.accent,
        enable_subtitles=project.enable_subtitles,
        created_at=project.created_at,
        updated_at=project.updated_at,
        uploaded_page_url=uploaded_url,
        expressions=[MathExpressionOut.model_validate(e) for e in project.math_expressions],
        lesson_plan=lesson,
        script=script,
        scenes=[SceneOut.model_validate(s) for s in project.scenes],
        jobs=[JobOut.model_validate(j) for j in project.jobs],
        videos=videos,
        subtitles=subs,
        ocr_reviewed=ocr_reviewed,
    )


@router.get("", response_model=list[ProjectSummary])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    user = get_or_create_default_user(db)
    projects = (
        db.query(Project)
        .filter(Project.user_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    storage = get_storage()
    out: list[ProjectSummary] = []
    for p in projects:
        thumb = None
        if p.uploaded_files:
            key = p.uploaded_files[0].processed_storage_key or p.uploaded_files[0].storage_key
            thumb = storage.presigned_url(key)
        out.append(
            ProjectSummary(
                id=p.id,
                title=p.title,
                status=p.status,
                progress_percent=p.progress_percent,
                progress_stage=p.progress_stage,
                error_message=p.error_message,
                created_at=p.created_at,
                updated_at=p.updated_at,
                has_video=any(v.is_primary for v in p.video_assets),
                thumbnail_url=thumb,
            )
        )
    return out


@router.post("", response_model=ProjectDetail)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectDetail:
    user = get_or_create_default_user(db)
    project = Project(
        user_id=user.id,
        title=payload.title,
        voice_gender=payload.voice_gender,
        voice_speed=payload.voice_speed,
        language=payload.language,
        accent=payload.accent,
        enable_subtitles=payload.enable_subtitles,
        status=ProjectStatus.CREATED,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return serialize_project(db, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: UUID, db: Session = Depends(get_db)) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return serialize_project(db, project)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: UUID, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return serialize_project(db, project)


@router.delete("/{project_id}")
def delete_project(project_id: UUID, db: Session = Depends(get_db)) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    storage = get_storage()
    storage.delete_prefix(f"projects/{project_id}")
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/{project_id}/generate", response_model=ProjectDetail)
def generate(project_id: UUID, payload: GenerateRequest, db: Session = Depends(get_db)) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.ocr_results or not project.ocr_results[-1].reviewed:
        raise HTTPException(400, "Please review and approve OCR results before generating")
    if project.status in (
        ProjectStatus.ANALYZING,
        ProjectStatus.VISUALIZING,
        ProjectStatus.NARRATION_GENERATED,
        ProjectStatus.RENDERING,
        ProjectStatus.PROCESSING,
    ):
        raise HTTPException(409, "Generation already in progress")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    # Seed jobs
    for stage in (
        JobStage.UNDERSTANDING,
        JobStage.SCRIPT,
        JobStage.SCENES,
        JobStage.VOICE,
        JobStage.MATHVIZ,
        JobStage.RENDER,
        JobStage.FINALIZE,
    ):
        db.add(
            GenerationJob(
                project_id=project.id,
                stage=stage,
                status=JobStatus.PENDING,
                progress_percent=0,
            )
        )
    project.status = ProjectStatus.ANALYZING
    project.progress_percent = 16
    project.progress_stage = "UNDERSTANDING"
    project.error_message = None
    db.commit()

    from app.workers.pipeline import generate_video

    task = generate_video.delay(str(project.id))
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.stage == JobStage.UNDERSTANDING)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if job:
        job.celery_task_id = task.id
        db.commit()

    db.refresh(project)
    return serialize_project(db, project)
