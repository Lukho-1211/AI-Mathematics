"""Tests for generation job dedupe / latest-per-stage serialization helpers."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.generation_jobs import GENERATION_STAGES, ensure_generation_jobs, latest_jobs_by_stage
from app.models import JobStage, JobStatus


def _job(stage: JobStage, status: JobStatus, *, created_at: datetime, project_id=None):
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id or uuid4(),
        stage=stage,
        status=status,
        progress_percent=0 if status == JobStatus.PENDING else 100,
        message=None,
        error_message=None,
        celery_task_id=None,
        started_at=None,
        finished_at=None,
        created_at=created_at,
    )


class _FakeSession:
    def __init__(self):
        self.added: list = []
        self.deleted: list = []

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)


def test_latest_jobs_by_stage_keeps_newest():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=5)
    jobs = [
        _job(JobStage.SCENES, JobStatus.PENDING, created_at=t0),
        _job(JobStage.SCENES, JobStatus.COMPLETED, created_at=t1),
        _job(JobStage.VOICE, JobStatus.RUNNING, created_at=t1),
        _job(JobStage.SCRIPT, JobStatus.COMPLETED, created_at=t0),
    ]
    latest = latest_jobs_by_stage(jobs)
    by_stage = {j.stage: j for j in latest}
    assert by_stage[JobStage.SCENES].status == JobStatus.COMPLETED
    assert by_stage[JobStage.VOICE].status == JobStatus.RUNNING
    assert len([j for j in latest if j.stage == JobStage.SCENES]) == 1


def test_ensure_generation_jobs_resets_and_dedupes():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)
    project_id = uuid4()
    old_scenes = _job(JobStage.SCENES, JobStatus.COMPLETED, created_at=t0, project_id=project_id)
    new_scenes = _job(JobStage.SCENES, JobStatus.FAILED, created_at=t1, project_id=project_id)
    script = _job(JobStage.SCRIPT, JobStatus.COMPLETED, created_at=t0, project_id=project_id)

    project = SimpleNamespace(id=project_id, jobs=[old_scenes, new_scenes, script])
    db = _FakeSession()
    ensure_generation_jobs(db, project)

    assert old_scenes in db.deleted
    assert new_scenes.status == JobStatus.PENDING
    assert new_scenes.progress_percent == 0
    assert new_scenes.error_message is None
    assert script.status == JobStatus.PENDING

    seeded_stages = {j.stage for j in db.added}
    # SCRIPT and SCENES already existed; other generation stages should be created
    expected_missing = set(GENERATION_STAGES) - {JobStage.SCRIPT, JobStage.SCENES}
    assert seeded_stages == expected_missing
