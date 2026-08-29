"""ORM models for the mathematics video generation pipeline."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class ProjectStatus(str, enum.Enum):
    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    OCR_COMPLETE = "OCR_COMPLETE"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    ANALYZING = "ANALYZING"
    SCRIPT_GENERATED = "SCRIPT_GENERATED"
    VISUALIZING = "VISUALIZING"
    NARRATION_GENERATED = "NARRATION_GENERATED"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobStage(str, enum.Enum):
    UPLOAD = "UPLOAD"
    OCR = "OCR"
    REVIEW = "REVIEW"
    UNDERSTANDING = "UNDERSTANDING"
    SCRIPT = "SCRIPT"
    SCENES = "SCENES"
    VOICE = "VOICE"
    MATHVIZ = "MATHVIZ"
    RENDER = "RENDER"
    FINALIZE = "FINALIZE"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ElementType(str, enum.Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    EQUATION = "equation"
    EXAMPLE = "example"
    QUESTION = "question"
    SOLUTION = "solution"
    DEFINITION = "definition"
    NOTE = "note"
    TABLE = "table"
    DIAGRAM = "diagram"
    VARIABLE = "variable"
    OTHER = "other"


class SceneType(str, enum.Enum):
    TITLE_CARD = "title_card"
    TEXTBOOK_PAGE = "textbook_page"
    CONCEPT = "concept"
    ALGEBRA_STEPS = "algebra_steps"
    GRAPH_2D = "graph_2d"
    GEOMETRY = "geometry"
    NUMBER_LINE = "number_line"
    MATRIX = "matrix"
    WHY_EXPLANATION = "why_explanation"
    SUMMARY_CARD = "summary_card"
    PRACTICE = "practice"
    CUSTOM = "custom"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="Demo User")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list[Project]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="Untitled Lesson")
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        default=ProjectStatus.CREATED,
        nullable=False,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    voice_gender: Mapped[str] = mapped_column(String(16), default="female")
    voice_speed: Mapped[float] = mapped_column(Float, default=1.0)
    language: Mapped[str] = mapped_column(String(16), default="en")
    accent: Mapped[str] = mapped_column(String(32), default="american")
    enable_subtitles: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="projects")
    uploaded_files: Mapped[list[UploadedFile]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    ocr_results: Mapped[list[OCRResult]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    math_expressions: Mapped[list[MathExpression]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    lesson_plan: Mapped[Optional[LessonPlan]] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    script: Mapped[Optional[Script]] = relationship(
        back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    scenes: Mapped[list[Scene]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Scene.order_index"
    )
    jobs: Mapped[list[GenerationJob]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    audio_assets: Mapped[list[AudioAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    visualization_assets: Mapped[list[VisualizationAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    video_assets: Mapped[list[VideoAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    subtitle_assets: Mapped[list[SubtitleAsset]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    processed_storage_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int] = mapped_column(Integer, default=1)
    crop_box: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="uploaded_files")


class OCRResult(Base):
    __tablename__ = "ocr_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    full_text: Mapped[str] = mapped_column(Text, default="")
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="ocr_results")


class MathExpression(Base):
    __tablename__ = "math_expressions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    element_type: Mapped[ElementType] = mapped_column(
        Enum(ElementType, name="element_type"), default=ElementType.OTHER
    )
    original_text: Mapped[str] = mapped_column(Text, default="")
    latex: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bbox: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    page_location: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    user_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_authoritative: Mapped[bool] = mapped_column(Boolean, default=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="math_expressions")


class LessonPlan(Base):
    __tablename__ = "lesson_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), unique=True, nullable=False
    )
    topic: Mapped[str] = mapped_column(String(512), default="")
    learning_objectives: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    concepts: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    prerequisites: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    sections: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    teaching_sequence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    visualization_candidates: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="lesson_plan")


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), unique=True, nullable=False
    )
    full_script: Mapped[str] = mapped_column(Text, default="")
    segments: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="script")


class Scene(Base):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("project_id", "scene_id", name="uq_project_scene_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    scene_type: Mapped[SceneType] = mapped_column(
        Enum(SceneType, name="scene_type"), default=SceneType.CUSTOM
    )
    title: Mapped[str] = mapped_column(String(512), default="")
    narration: Mapped[str] = mapped_column(Text, default="")
    duration_target: Mapped[float] = mapped_column(Float, default=20.0)
    duration_actual: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    visualization_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="scenes")


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage, name="job_stage"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.PENDING
    )
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="jobs")


class AudioAsset(Base):
    __tablename__ = "audio_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scene_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    voice: Mapped[str] = mapped_column(String(64), default="")
    format: Mapped[str] = mapped_column(String(16), default="mp3")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="audio_assets")


class VisualizationAsset(Base):
    __tablename__ = "visualization_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    scene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    manim_code_key: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="mathviz_ai")
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="visualization_assets")


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    resolution: Mapped[str] = mapped_column(String(16), default="1080p")
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    codec_video: Mapped[str] = mapped_column(String(32), default="h264")
    codec_audio: Mapped[str] = mapped_column(String(32), default="aac")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="video_assets")


class SubtitleAsset(Base):
    __tablename__ = "subtitle_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="srt")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="subtitle_assets")
