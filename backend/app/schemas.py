"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import ElementType, JobStage, JobStatus, ProjectStatus, SceneType


class ProjectCreate(BaseModel):
    title: str = "Untitled Lesson"
    voice_gender: str = "female"
    voice_speed: float = 1.0
    language: str = "en"
    accent: str = "american"
    enable_subtitles: bool = True
    term: Optional[int] = Field(default=None, ge=1, le=4)
    week: Optional[int] = Field(default=None, ge=1, le=14)


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    voice_gender: Optional[str] = None
    voice_speed: Optional[float] = None
    language: Optional[str] = None
    accent: Optional[str] = None
    enable_subtitles: Optional[bool] = None
    term: Optional[int] = Field(default=None, ge=1, le=4)
    week: Optional[int] = Field(default=None, ge=1, le=14)


class CropBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class UploadTransform(BaseModel):
    crop: Optional[CropBox] = None
    rotation: int = 0
    page_number: int = 1


class MathExpressionOut(BaseModel):
    id: UUID
    element_type: ElementType
    original_text: str
    latex: Optional[str] = None
    bbox: Optional[dict[str, Any]] = None
    page_location: Optional[str] = None
    confidence: float
    needs_review: bool
    user_corrected: bool
    order_index: int

    model_config = {"from_attributes": True}


class MathExpressionUpdate(BaseModel):
    original_text: Optional[str] = None
    latex: Optional[str] = None
    element_type: Optional[ElementType] = None


class ExpressionReviewPayload(BaseModel):
    expressions: list[dict[str, Any]]


class SceneOut(BaseModel):
    id: UUID
    scene_id: str
    order_index: int
    scene_type: SceneType
    title: str
    narration: str
    duration_target: float
    duration_actual: Optional[float] = None
    visualization_spec: dict[str, Any]
    status: str
    error_message: Optional[str] = None
    preview_url: Optional[str] = None

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: UUID
    stage: JobStage
    status: JobStatus
    progress_percent: int
    message: Optional[str] = None
    error_message: Optional[str] = None

    model_config = {"from_attributes": True}


class VideoAssetOut(BaseModel):
    id: UUID
    resolution: str
    duration_sec: float
    url: Optional[str] = None
    is_primary: bool
    validated: bool

    model_config = {"from_attributes": True}


class SubtitleAssetOut(BaseModel):
    id: UUID
    format: str
    url: Optional[str] = None

    model_config = {"from_attributes": True}


class LessonPlanOut(BaseModel):
    topic: str
    learning_objectives: list[Any]
    concepts: list[Any]
    prerequisites: list[Any]
    sections: list[Any]
    teaching_sequence: list[Any]
    visualization_candidates: list[Any]

    model_config = {"from_attributes": True}


class ScriptOut(BaseModel):
    full_script: str
    segments: list[Any]

    model_config = {"from_attributes": True}


class ProjectSummary(BaseModel):
    id: UUID
    title: str
    status: ProjectStatus
    progress_percent: int
    progress_stage: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    has_video: bool = False
    thumbnail_url: Optional[str] = None
    term: Optional[int] = None
    week: Optional[int] = None

    model_config = {"from_attributes": True}


class UploadedPageOut(BaseModel):
    filename: str
    url: str


class ProjectDetail(BaseModel):
    id: UUID
    title: str
    status: ProjectStatus
    progress_percent: int
    progress_stage: Optional[str] = None
    error_message: Optional[str] = None
    voice_gender: str
    voice_speed: float
    language: str
    accent: str
    enable_subtitles: bool
    term: Optional[int] = None
    week: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    uploaded_page_url: Optional[str] = None
    uploaded_pages: list[UploadedPageOut] = Field(default_factory=list)
    expressions: list[MathExpressionOut] = Field(default_factory=list)
    lesson_plan: Optional[LessonPlanOut] = None
    script: Optional[ScriptOut] = None
    scenes: list[SceneOut] = Field(default_factory=list)
    jobs: list[JobOut] = Field(default_factory=list)
    videos: list[VideoAssetOut] = Field(default_factory=list)
    subtitles: list[SubtitleAssetOut] = Field(default_factory=list)
    ocr_reviewed: bool = False

    model_config = {"from_attributes": True}


class ProgressEvent(BaseModel):
    project_id: UUID
    stage: str
    status: str
    progress_percent: int
    message: Optional[str] = None
    error_message: Optional[str] = None


class GenerateRequest(BaseModel):
    voice_gender: Optional[str] = None
    voice_speed: Optional[float] = None
    language: Optional[str] = None
    accent: Optional[str] = None
    enable_subtitles: Optional[bool] = None
