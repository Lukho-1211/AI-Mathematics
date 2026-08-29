"""Redis-backed progress publishing for SSE clients."""

from __future__ import annotations

import json
from typing import Any, Optional
from uuid import UUID

import redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def progress_channel(project_id: UUID | str) -> str:
    return f"project:{project_id}:progress"


class ProgressPublisher:
    def __init__(self) -> None:
        settings = get_settings()
        self.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def publish(
        self,
        project_id: UUID | str,
        *,
        stage: str,
        status: str,
        progress_percent: int,
        message: Optional[str] = None,
        error_message: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project_id": str(project_id),
            "stage": stage,
            "status": status,
            "progress_percent": int(progress_percent),
            "message": message,
            "error_message": error_message,
        }
        if extra:
            payload.update(extra)
        channel = progress_channel(project_id)
        self.redis.publish(channel, json.dumps(payload))
        # Also store latest snapshot
        self.redis.set(f"project:{project_id}:progress:latest", json.dumps(payload), ex=86400)
        logger.info(
            "progress %s stage=%s status=%s pct=%s",
            project_id,
            stage,
            status,
            progress_percent,
        )
        return payload

    def latest(self, project_id: UUID | str) -> Optional[dict[str, Any]]:
        raw = self.redis.get(f"project:{project_id}:progress:latest")
        if not raw:
            return None
        return json.loads(raw)


def get_progress_publisher() -> ProgressPublisher:
    return ProgressPublisher()
