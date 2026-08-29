"""Text-to-speech narration via OpenAI TTS."""

from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AudioResult:
    path: Path
    duration_sec: float
    voice: str
    format: str = "mp3"


class VoiceService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_tts_model

    def resolve_voice(self, gender: str) -> str:
        g = (gender or "female").lower()
        if g in ("male", "m"):
            return self.settings.openai_tts_voice_male
        return self.settings.openai_tts_voice_female

    def synthesize(
        self,
        text: str,
        *,
        gender: str = "female",
        speed: float = 1.0,
        language: str = "en",
        out_path: Path | None = None,
    ) -> AudioResult:
        if not self.settings.openai_api_key or self.settings.openai_api_key.startswith("sk-your-"):
            raise RuntimeError(
                "OPENAI_API_KEY is not configured. Set a real key in .env and restart api/worker."
            )
        if not text.strip():
            raise ValueError("Cannot synthesize empty narration")

        voice = self.resolve_voice(gender)
        speed = max(0.5, min(1.5, float(speed)))

        # OpenAI TTS speed param supported on newer models; clamp safely
        kwargs: dict = {
            "model": self.model,
            "voice": voice,
            "input": text,
            "response_format": "mp3",
        }
        # gpt-4o-mini-tts / tts-1 support speed
        try:
            kwargs["speed"] = speed
        except Exception:
            pass

        logger.info("Synthesizing TTS voice=%s model=%s chars=%s", voice, self.model, len(text))
        # Some model names may not accept speed — retry without
        try:
            response = self.client.audio.speech.create(**kwargs)
        except Exception as exc:
            logger.warning("TTS with speed failed (%s); retrying without speed", exc)
            kwargs.pop("speed", None)
            response = self.client.audio.speech.create(**kwargs)

        if out_path is None:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            out_path = Path(tmp.name)
            tmp.close()

        out_path.parent.mkdir(parents=True, exist_ok=True)
        # openai SDK BinaryAPIResponse
        if hasattr(response, "stream_to_file"):
            response.stream_to_file(str(out_path))
        elif hasattr(response, "write_to_file"):
            response.write_to_file(str(out_path))
        else:
            out_path.write_bytes(response.content)
        if not out_path.exists() or out_path.stat().st_size < 100:
            raise RuntimeError("TTS produced empty audio file")
        duration = probe_audio_duration(out_path)
        return AudioResult(path=out_path, duration_sec=duration, voice=voice, format="mp3")


def probe_audio_duration(path: Path) -> float:
    """Return duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return float(out)
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s; estimating from size", path, exc)
        # Rough estimate: 16kbps mp3 ~ 2KB/s
        size = path.stat().st_size
        return max(1.0, size / 2000.0)
