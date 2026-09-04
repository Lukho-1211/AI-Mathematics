"""Helpers for generation job rows (one per stage, latest wins)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import GenerationJob, JobStage, JobStatus, Project

GENERATION_STAGES = (
    JobStage.UNDERSTANDING,
    JobStage.SCRIPT,
    JobStage.SCENES,
    JobStage.VOICE,
    JobStage.MATHVIZ,
    JobStage.RENDER,
    JobStage.FINALIZE,
)


def latest_jobs_by_stage(jobs: list[Any]) -> list[Any]:
    """Return one job per stage — the newest by created_at (same rule as _set_job)."""
    by_stage: dict[Any, Any] = {}
    for job in sorted(
        jobs,
        key=lambda j: (j.created_at is None, j.created_at or datetime.min.replace(tzinfo=timezone.utc)),
    ):
        by_stage[job.stage] = job
    ordered: list[Any] = []
    seen: set[Any] = set()
    for stage in (
        JobStage.UPLOAD,
        JobStage.OCR,
        JobStage.REVIEW,
        *GENERATION_STAGES,
    ):
        if stage in by_stage:
            ordered.append(by_stage[stage])
            seen.add(stage)
    for stage, job in by_stage.items():
        if stage not in seen:
            ordered.append(job)
    return ordered


def ensure_generation_jobs(db: Session, project: Project) -> None:
    """Reuse or reset one PENDING job row per post-review stage (no duplicates)."""
    by_stage: dict[JobStage, list[GenerationJob]] = {}
    for job in project.jobs:
        if job.stage in GENERATION_STAGES:
            by_stage.setdefault(job.stage, []).append(job)

    for stage in GENERATION_STAGES:
        rows = sorted(
            by_stage.get(stage, []),
            key=lambda j: (j.created_at is None, j.created_at or datetime.min.replace(tzinfo=timezone.utc)),
        )
        if not rows:
            db.add(
                GenerationJob(
                    project_id=project.id,
                    stage=stage,
                    status=JobStatus.PENDING,
                    progress_percent=0,
                    message=None,
                    error_message=None,
                    celery_task_id=None,
                    started_at=None,
                    finished_at=None,
                )
            )
            continue
        keep = rows[-1]
        for stale in rows[:-1]:
            db.delete(stale)
        keep.status = JobStatus.PENDING
        keep.progress_percent = 0
        keep.message = None
        keep.error_message = None
        keep.celery_task_id = None
        keep.started_at = None
        keep.finished_at = None
