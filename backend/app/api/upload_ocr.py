"""Upload and OCR / review endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import (
    ElementType,
    GenerationJob,
    JobStage,
    JobStatus,
    MathExpression,
    OCRResult,
    Project,
    ProjectStatus,
    UploadedFile,
)
from app.schemas import (
    ExpressionReviewPayload,
    MathExpressionOut,
    MathExpressionUpdate,
    ProjectDetail,
)
from app.services.image_processing import (
    ALLOWED_CONTENT_TYPES,
    apply_transform,
    detect_content_type,
    pdf_page_to_png,
)
from app.services.storage import get_storage
from app.api.projects import serialize_project

router = APIRouter(tags=["upload", "ocr"])


@router.post("/api/upload/{project_id}", response_model=ProjectDetail)
async def upload_file(
    project_id: UUID,
    file: UploadFile = File(...),
    rotation: int = Form(0),
    page_number: int = Form(1),
    crop_json: str | None = Form(None),
    db: Session = Depends(get_db),
) -> ProjectDetail:
    settings = get_settings()
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    data = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(400, f"File exceeds {settings.max_upload_mb}MB limit")
    if len(data) == 0:
        raise HTTPException(400, "Empty file")

    declared = (file.content_type or "").lower()
    filename = file.filename or "upload.bin"
    try:
        content_type = detect_content_type(data, declared, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if content_type not in ALLOWED_CONTENT_TYPES and content_type != "image/jpeg":
        raise HTTPException(400, f"Unsupported content type: {content_type}")

    crop = None
    if crop_json:
        try:
            crop = json.loads(crop_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "Invalid crop_json") from exc

    try:
        if content_type == "application/pdf":
            image_bytes = pdf_page_to_png(data, page_number=page_number)
        else:
            image_bytes = data
        processed, width, height = apply_transform(
            image_bytes, rotation=rotation % 360, crop=crop
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Failed to process file: {exc}") from exc

    storage = get_storage()
    original_key = storage.project_key(project_id, "original", filename)
    processed_key = storage.project_key(project_id, "original", "page.png")
    storage.upload_bytes(original_key, data, content_type)
    storage.upload_bytes(processed_key, processed, "image/png")

    # Replace prior uploads
    for uf in list(project.uploaded_files):
        db.delete(uf)
    db.flush()

    uf = UploadedFile(
        project_id=project.id,
        original_filename=filename,
        content_type=content_type,
        storage_key=original_key,
        processed_storage_key=processed_key,
        width=width,
        height=height,
        page_number=page_number,
        crop_box=crop,
        rotation=rotation % 360,
        file_size_bytes=len(data),
    )
    db.add(uf)
    project.status = ProjectStatus.UPLOADED
    project.progress_percent = 5
    project.progress_stage = "UPLOAD"
    project.error_message = None
    db.commit()
    db.refresh(project)
    return serialize_project(db, project)


@router.post("/api/ocr/{project_id}", response_model=ProjectDetail)
def start_ocr(project_id: UUID, db: Session = Depends(get_db)) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.uploaded_files:
        raise HTTPException(400, "Upload a textbook page first")

    db.add(
        GenerationJob(
            project_id=project.id,
            stage=JobStage.OCR,
            status=JobStatus.PENDING,
            message="Queued OCR",
        )
    )
    project.status = ProjectStatus.PROCESSING
    project.progress_stage = "OCR"
    project.progress_percent = 8
    project.error_message = None
    db.commit()

    from app.workers.pipeline import run_ocr

    task = run_ocr.delay(str(project.id))
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project.id, GenerationJob.stage == JobStage.OCR)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if job:
        job.celery_task_id = task.id
        db.commit()

    db.refresh(project)
    return serialize_project(db, project)


@router.get("/api/ocr/{project_id}/expressions", response_model=list[MathExpressionOut])
def list_expressions(project_id: UUID, db: Session = Depends(get_db)) -> list[MathExpressionOut]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return [MathExpressionOut.model_validate(e) for e in project.math_expressions]


@router.patch("/api/ocr/{project_id}/expressions/{expression_id}", response_model=MathExpressionOut)
def update_expression(
    project_id: UUID,
    expression_id: UUID,
    payload: MathExpressionUpdate,
    db: Session = Depends(get_db),
) -> MathExpressionOut:
    expr = db.get(MathExpression, expression_id)
    if not expr or expr.project_id != project_id:
        raise HTTPException(404, "Expression not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expr, field, value)
    expr.user_corrected = True
    expr.needs_review = False
    expr.confidence = 1.0
    db.commit()
    db.refresh(expr)
    return MathExpressionOut.model_validate(expr)


@router.post("/api/ocr/{project_id}/review", response_model=ProjectDetail)
def approve_review(
    project_id: UUID,
    payload: ExpressionReviewPayload | None = None,
    db: Session = Depends(get_db),
) -> ProjectDetail:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if not project.ocr_results:
        raise HTTPException(400, "No OCR result to review")

    if payload and payload.expressions:
        by_id = {str(e.id): e for e in project.math_expressions}
        for item in payload.expressions:
            eid = str(item.get("id"))
            expr = by_id.get(eid)
            if not expr:
                continue
            if "original_text" in item:
                expr.original_text = item["original_text"]
            if "latex" in item:
                expr.latex = item["latex"]
            if "element_type" in item:
                try:
                    expr.element_type = ElementType(item["element_type"])
                except Exception:
                    pass
            expr.user_corrected = True
            expr.needs_review = False
            expr.confidence = 1.0

    # Block if any still need review
    pending = [e for e in project.math_expressions if e.needs_review]
    if pending:
        raise HTTPException(
            400,
            f"{len(pending)} expression(s) still flagged for review. Correct them before approving.",
        )

    ocr = project.ocr_results[-1]
    ocr.reviewed = True
    ocr.reviewed_at = datetime.now(timezone.utc)
    project.status = ProjectStatus.OCR_COMPLETE
    project.progress_percent = 15
    project.progress_stage = "REVIEW"
    db.commit()
    db.refresh(project)
    return serialize_project(db, project)
