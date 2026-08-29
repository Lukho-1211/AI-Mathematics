"""FFmpeg-based video assembly and subtitle generation."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AssembledVideo:
    path_1080: Path
    path_720: Optional[Path]
    duration_sec: float


class VideoRenderService:
    def mux_scene(self, video_path: Path, audio_path: Path, out_path: Path, duration: float) -> Path:
        """Combine silent visualization with narration; pad/trim video to match audio."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Scale to 1920x1080, pad letterbox, loop/trim video to audio length
        filter_complex = (
            "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "1:a:0",
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(out_path),
        ]
        self._run(cmd)
        return out_path

    def concat_scenes(self, scene_videos: list[Path], out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = out_path.parent / "concat_list.txt"
        lines = []
        for p in scene_videos:
            # Escape single quotes for concat demuxer
            escaped = str(p.resolve()).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        self._run(cmd)
        return out_path

    def transcode_720(self, src: Path, out_path: Path) -> Path:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libx264",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        self._run(cmd)
        return out_path

    def assemble(
        self,
        scene_pairs: list[tuple[Path, Path, float]],
        work_dir: Path,
    ) -> AssembledVideo:
        work_dir.mkdir(parents=True, exist_ok=True)
        muxed: list[Path] = []
        total = 0.0
        for i, (v, a, dur) in enumerate(scene_pairs):
            out = work_dir / f"scene_{i:02d}_muxed.mp4"
            # If video is shorter than audio, tpad freeze last frame
            padded = work_dir / f"scene_{i:02d}_padded.mp4"
            self._pad_video_to_duration(v, padded, dur)
            self.mux_scene(padded, a, out, dur)
            muxed.append(out)
            total += dur

        out_1080 = work_dir / "final_1080p.mp4"
        self.concat_scenes(muxed, out_1080)
        out_720 = work_dir / "final_720p.mp4"
        try:
            self.transcode_720(out_1080, out_720)
        except Exception as exc:
            logger.warning("720p transcode failed: %s", exc)
            out_720 = None  # type: ignore

        duration = probe_duration(out_1080) or total
        return AssembledVideo(path_1080=out_1080, path_720=out_720, duration_sec=duration)

    def _pad_video_to_duration(self, src: Path, out: Path, duration: float) -> Path:
        src_dur = probe_duration(src) or 1.0
        if src_dur >= duration - 0.05:
            # Trim
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-t",
                f"{duration:.3f}",
                "-c",
                "copy",
                str(out),
            ]
            try:
                self._run(cmd)
                return out
            except Exception:
                pass
        # Freeze last frame to extend
        pad = max(0.0, duration - src_dur)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={pad:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            f"{duration:.3f}",
            str(out),
        ]
        self._run(cmd)
        return out

    @staticmethod
    def _run(cmd: list[str]) -> None:
        logger.info("ffmpeg: %s", " ".join(cmd[:8]) + "...")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            logger.error("ffmpeg stderr: %s", proc.stderr[-2000:])
            raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")


def probe_duration(path: Path) -> Optional[float]:
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
    except Exception:
        return None


def probe_streams(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    return json.loads(out)


class SubtitleService:
    def build_srt(self, segments: list[dict[str, Any]]) -> str:
        """segments: [{start, end, text}]"""
        lines: list[str] = []
        for i, seg in enumerate(segments, start=1):
            lines.append(str(i))
            lines.append(f"{_ts(seg['start'])} --> {_ts(seg['end'])}")
            lines.append(seg["text"].replace("\n", " ").strip())
            lines.append("")
        return "\n".join(lines)

    def build_vtt(self, segments: list[dict[str, Any]]) -> str:
        lines = ["WEBVTT", ""]
        for seg in segments:
            lines.append(f"{_ts_vtt(seg['start'])} --> {_ts_vtt(seg['end'])}")
            lines.append(seg["text"].replace("\n", " ").strip())
            lines.append("")
        return "\n".join(lines)

    def from_scene_audio(
        self, scenes: list[dict[str, Any]]
    ) -> tuple[str, str]:
        """scenes with narration + duration_actual, sequential."""
        segments: list[dict[str, Any]] = []
        t = 0.0
        for sc in scenes:
            dur = float(sc.get("duration_actual") or sc.get("duration_target") or 5.0)
            text = (sc.get("narration") or "").strip()
            if text:
                segments.append({"start": t, "end": t + dur, "text": text})
            t += dur
        return self.build_srt(segments), self.build_vtt(segments)


def _ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
