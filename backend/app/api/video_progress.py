"""Progress SSE, video downloads, and misc API routes."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator
from uuid import UUID

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Project, SubtitleAsset, VideoAsset
from app.services.progress import progress_channel
from app.services.storage import get_storage

router = APIRouter(tags=["progress", "video"])


def _terminal_status(payload: str | None) -> bool:
    if not payload:
        return False
    try:
        status = json.loads(payload).get("status")
    except Exception:
        return False
    return status in ("COMPLETED", "FAILED")


@router.get("/api/progress/{project_id}")
async def progress_sse(project_id: UUID) -> EventSourceResponse:
    settings = get_settings()

    async def event_generator() -> AsyncGenerator[dict, None]:
        r = redis.from_url(settings.redis_url, decode_responses=True)
        pubsub = r.pubsub()
        channel = progress_channel(project_id)
        await pubsub.subscribe(channel)
        latest = await r.get(f"project:{project_id}:progress:latest")
        # #region agent log
        try:
            import json as _json, time as _time
            _p = {"sessionId":"820bf8","hypothesisId":"F","location":"video_progress.py:progress_sse","message":"sse_start","data":{"project_id":str(project_id),"has_latest":bool(latest),"terminal":_terminal_status(latest)},"timestamp":int(_time.time()*1000),"runId":"post-fix"}
            with open("/app/debug-820bf8.log","a",encoding="utf-8") as _f:
                _f.write(_json.dumps(_p)+"\n")
        except Exception:
            pass
        # #endregion
        if latest:
            yield {"event": "progress", "data": latest}
            if _terminal_status(latest):
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
                await r.aclose()
                return
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if not data:
                    continue
                yield {"event": "progress", "data": data}
                if _terminal_status(data if isinstance(data, str) else json.dumps(data)):
                    await asyncio.sleep(0.5)
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await r.aclose()

    return EventSourceResponse(event_generator())


@router.get("/api/video/{project_id}")
def get_primary_video(project_id: UUID, db: Session = Depends(get_db)) -> RedirectResponse:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    video = next((v for v in project.video_assets if v.is_primary), None)
    if not video:
        video = project.video_assets[0] if project.video_assets else None
    if not video:
        raise HTTPException(404, "Video not ready")
    url = get_storage().presigned_url(video.storage_key)
    return RedirectResponse(url)


@router.get("/api/video/{project_id}/download")
def download_video(
    project_id: UUID, resolution: str = "1080p", db: Session = Depends(get_db)
) -> StreamingResponse:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    video = next((v for v in project.video_assets if v.resolution == resolution), None)
    if not video:
        video = next((v for v in project.video_assets if v.is_primary), None)
    if not video:
        raise HTTPException(404, "Video not found")
    storage = get_storage()
    filename = f"mathviz_{project_id}_{video.resolution}.mp4"
    return StreamingResponse(
        storage.iter_object(video.storage_key),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/video/{project_id}/subtitles/{fmt}")
def download_subtitles(
    project_id: UUID, fmt: str, db: Session = Depends(get_db)
) -> StreamingResponse:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    fmt = fmt.lower()
    if fmt not in ("srt", "vtt"):
        raise HTTPException(400, "format must be srt or vtt")
    sub = next((s for s in project.subtitle_assets if s.format == fmt), None)
    if not sub:
        raise HTTPException(404, "Subtitles not found")
    storage = get_storage()
    media_type = "text/vtt" if fmt == "vtt" else "application/x-subrip"
    filename = f"mathviz_{project_id}.{fmt}"
    return StreamingResponse(
        storage.iter_object(sub.storage_key),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/video/{project_id}/lesson")
def download_lesson(project_id: UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    storage = get_storage()
    key = storage.project_key(project_id, "lesson", "lesson.md")
    if not storage.exists(key):
        raise HTTPException(404, "Lesson export not found")
    filename = f"mathviz_{project_id}_lesson.md"
    return StreamingResponse(
        storage.iter_object(key),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
