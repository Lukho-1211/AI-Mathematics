"""End-to-end asynchronous video generation pipeline."""

from __future__ import annotations

import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from app.core.database import SessionLocal
from app.core.logging import get_logger, setup_logging
from app.models import (
    AudioAsset,
    ElementType,
    GenerationJob,
    JobStage,
    JobStatus,
    LessonPlan,
    MathExpression,
    OCRResult,
    Project,
    ProjectStatus,
    Scene,
    SceneType,
    Script,
    SubtitleAsset,
    VideoAsset,
    VisualizationAsset,
)
from app.services.ocr import OCRService
from app.services.progress import get_progress_publisher
from app.services.providers.mathviz_ai import MathVizService
from app.services.quality import QualityControlService
from app.services.storage import get_storage
from app.services.understanding import (
    LessonPlanService,
    MathUnderstandingService,
    SceneSpecService,
    ScriptService,
    sanitize_scenes,
)
from app.services.video_render import SubtitleService, VideoRenderService
from app.services.voice import VoiceService
from app.workers.celery_app import celery_app

setup_logging()
logger = get_logger(__name__)


STAGE_WEIGHTS = {
    JobStage.OCR: (0, 15),
    JobStage.UNDERSTANDING: (15, 30),
    JobStage.SCRIPT: (30, 42),
    JobStage.SCENES: (42, 50),
    JobStage.VOICE: (50, 68),
    JobStage.MATHVIZ: (68, 88),
    JobStage.RENDER: (88, 97),
    JobStage.FINALIZE: (97, 100),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _map_element_type(raw: str) -> ElementType:
    try:
        return ElementType(raw.lower())
    except Exception:
        return ElementType.OTHER


def _map_scene_type(raw: str) -> SceneType:
    try:
        return SceneType(raw)
    except Exception:
        mapping = {
            "title": SceneType.TITLE_CARD,
            "overview": SceneType.TEXTBOOK_PAGE,
            "example": SceneType.ALGEBRA_STEPS,
            "summary": SceneType.SUMMARY_CARD,
        }
        return mapping.get((raw or "").lower(), SceneType.CUSTOM)


def _page_content_from_project(db, project: Project) -> dict[str, Any]:
    exprs = (
        db.query(MathExpression)
        .filter(MathExpression.project_id == project.id)
        .order_by(MathExpression.order_index)
        .all()
    )
    return {
        "title": project.title,
        "elements": [
            {
                "id": str(e.id),
                "element_type": e.element_type.value,
                "original_text": e.original_text,
                "latex": e.latex,
                "bbox": e.bbox,
                "confidence": e.confidence,
                "needs_review": e.needs_review,
            }
            for e in exprs
        ],
    }


def _set_job(
    db,
    project_id: UUID,
    stage: JobStage,
    status: JobStatus,
    percent: int,
    message: str | None = None,
    error: str | None = None,
) -> GenerationJob:
    job = (
        db.query(GenerationJob)
        .filter(GenerationJob.project_id == project_id, GenerationJob.stage == stage)
        .order_by(GenerationJob.created_at.desc())
        .first()
    )
    if job is None:
        job = GenerationJob(project_id=project_id, stage=stage)
        db.add(job)
    job.status = status
    job.progress_percent = percent
    job.message = message
    job.error_message = error
    if status == JobStatus.RUNNING and job.started_at is None:
        job.started_at = _utcnow()
    if status in (JobStatus.COMPLETED, JobStatus.FAILED):
        job.finished_at = _utcnow()
    db.commit()
    return job


def _update_project(
    db,
    project: Project,
    *,
    status: ProjectStatus | None = None,
    percent: int | None = None,
    stage: str | None = None,
    error: str | None = None,
) -> None:
    if status is not None:
        project.status = status
    if percent is not None:
        project.progress_percent = percent
    if stage is not None:
        project.progress_stage = stage
    if error is not None:
        project.error_message = error
    project.updated_at = _utcnow()
    db.commit()
    pub = get_progress_publisher()
    pub.publish(
        project.id,
        stage=stage or (project.progress_stage or ""),
        status=(status or project.status).value,
        progress_percent=project.progress_percent,
        message=None,
        error_message=project.error_message,
    )


@celery_app.task(name="pipeline.run_ocr", bind=True)
def run_ocr(self, project_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        project = db.get(Project, UUID(project_id))
        if not project:
            raise ValueError("Project not found")
        _set_job(db, project.id, JobStage.OCR, JobStatus.RUNNING, 5, "Reading textbook page(s)")
        _update_project(
            db, project, status=ProjectStatus.PROCESSING, percent=5, stage="OCR", error=None
        )

        storage = get_storage()
        uploaded_files = sorted(
            [u for u in project.uploaded_files if u.processed_storage_key],
            key=lambda u: (u.created_at is None, u.created_at),
        )
        if not uploaded_files:
            raise RuntimeError("No processed upload found for OCR")

        ocr = OCRService()
        page_results: list[dict[str, Any]] = []
        full_text_parts: list[str] = []
        all_elements: list[tuple[int, dict[str, Any]]] = []
        topic_guess: str | None = None

        for page_idx, uploaded in enumerate(uploaded_files, start=1):
            pct = 5 + int(80 * ((page_idx - 1) / max(1, len(uploaded_files))))
            _set_job(
                db,
                project.id,
                JobStage.OCR,
                JobStatus.RUNNING,
                pct,
                f"Reading textbook page {page_idx}/{len(uploaded_files)}",
            )
            image_bytes = storage.download_bytes(uploaded.processed_storage_key)
            result = ocr.extract(image_bytes)
            page_results.append(result)
            text = (result.get("full_text") or "").strip()
            if text:
                if len(uploaded_files) > 1:
                    full_text_parts.append(f"--- Page {page_idx} ---\n{text}")
                else:
                    full_text_parts.append(text)
            if not topic_guess and result.get("topic_guess"):
                topic_guess = result["topic_guess"]
            for el in result.get("elements") or []:
                all_elements.append((page_idx, el))

        # Persist OCR + expressions (replace previous)
        db.query(MathExpression).filter(MathExpression.project_id == project.id).delete()
        db.query(OCRResult).filter(OCRResult.project_id == project.id).delete()
        db.commit()

        merged = {
            "pages": page_results,
            "page_count": len(uploaded_files),
            "full_text": "\n\n".join(full_text_parts),
            "topic_guess": topic_guess,
            "elements": [
                {**el, "page_index": page_idx} for page_idx, el in all_elements
            ],
        }

        ocr_row = OCRResult(
            project_id=project.id,
            raw_response=merged,
            full_text=merged["full_text"],
            reviewed=False,
        )
        db.add(ocr_row)

        if topic_guess and (not project.title or project.title == "Untitled Lesson"):
            project.title = topic_guess

        for i, (page_idx, el) in enumerate(all_elements):
            loc = (el.get("page_location") or "").strip()
            if len(uploaded_files) > 1:
                page_location = f"page {page_idx} / {loc}" if loc else f"page {page_idx}"
            else:
                page_location = loc or None
            db.add(
                MathExpression(
                    project_id=project.id,
                    element_type=_map_element_type(el.get("element_type") or "other"),
                    original_text=el.get("original_text") or "",
                    latex=el.get("latex"),
                    bbox=el.get("bbox"),
                    page_location=page_location,
                    confidence=float(el.get("confidence") or 0.5),
                    needs_review=bool(el.get("needs_review")),
                    order_index=i,
                    is_authoritative=True,
                )
            )
        db.commit()

        # Store OCR JSON artifact
        key = storage.project_key(project.id, "ocr", "result.json")
        import json

        storage.upload_bytes(key, json.dumps(merged, indent=2).encode("utf-8"), "application/json")

        _set_job(db, project.id, JobStage.OCR, JobStatus.COMPLETED, 100, "OCR complete")
        _update_project(
            db,
            project,
            status=ProjectStatus.AWAITING_REVIEW,
            percent=15,
            stage="REVIEW",
        )
        return {"project_id": project_id, "elements": len(all_elements), "pages": len(uploaded_files)}
    except Exception as exc:
        logger.exception("OCR failed for %s", project_id)
        project = db.get(Project, UUID(project_id))
        if project:
            _set_job(
                db, project.id, JobStage.OCR, JobStatus.FAILED, 0, error=str(exc)
            )
            _update_project(
                db,
                project,
                status=ProjectStatus.FAILED,
                percent=project.progress_percent,
                stage="OCR",
                error=str(exc),
            )
        raise
    finally:
        db.close()


@celery_app.task(name="pipeline.generate_video", bind=True)
def generate_video(self, project_id: str) -> dict[str, Any]:
    """Full post-review pipeline: understand → script → scenes → voice → mathviz → render."""
    db = SessionLocal()
    storage = get_storage()
    qc = QualityControlService()
    try:
        project = db.get(Project, UUID(project_id))
        if not project:
            raise ValueError("Project not found")

        ocr_rows = project.ocr_results
        if not ocr_rows or not ocr_rows[-1].reviewed:
            raise RuntimeError("OCR must be reviewed and approved before generating video")

        page_content = _page_content_from_project(db, project)

        # --- Understanding + lesson ---
        _set_job(
            db, project.id, JobStage.UNDERSTANDING, JobStatus.RUNNING, 10, "Understanding mathematics"
        )
        _update_project(
            db, project, status=ProjectStatus.ANALYZING, percent=20, stage="UNDERSTANDING", error=None
        )

        understanding = MathUnderstandingService().analyze(page_content)
        if understanding.get("uncertainties"):
            logger.warning("Uncertainties flagged: %s", understanding["uncertainties"])

        lesson = LessonPlanService().create(understanding, page_content)
        if project.lesson_plan:
            db.delete(project.lesson_plan)
            db.commit()
        lp = LessonPlan(
            project_id=project.id,
            topic=lesson.get("topic") or project.title,
            learning_objectives=lesson.get("learning_objectives") or [],
            concepts=lesson.get("concepts") or [],
            prerequisites=lesson.get("prerequisites") or [],
            sections=lesson.get("sections") or [],
            teaching_sequence=lesson.get("teaching_sequence") or [],
            visualization_candidates=lesson.get("visualization_candidates") or [],
            raw_json={"understanding": understanding, "lesson": lesson},
        )
        db.add(lp)
        if lesson.get("topic"):
            project.title = lesson["topic"]
        db.commit()
        storage.upload_bytes(
            storage.project_key(project.id, "lesson", "lesson_plan.json"),
            __import__("json").dumps({"understanding": understanding, "lesson": lesson}, indent=2).encode(),
            "application/json",
        )
        _set_job(db, project.id, JobStage.UNDERSTANDING, JobStatus.COMPLETED, 100, "Lesson plan ready")

        # --- Script ---
        _set_job(db, project.id, JobStage.SCRIPT, JobStatus.RUNNING, 20, "Creating explanation")
        _update_project(db, project, percent=35, stage="SCRIPT")
        script_data = ScriptService().generate(
            lesson, understanding, page_content, language=project.language
        )
        if project.script:
            db.delete(project.script)
            db.commit()
        scr = Script(
            project_id=project.id,
            full_script=script_data.get("full_script") or "",
            segments=script_data.get("segments") or [],
            raw_json=script_data,
        )
        db.add(scr)
        db.commit()
        _set_job(db, project.id, JobStage.SCRIPT, JobStatus.COMPLETED, 100)
        _update_project(db, project, status=ProjectStatus.SCRIPT_GENERATED, percent=42, stage="SCENES")

        # --- Scene specs ---
        _set_job(db, project.id, JobStage.SCENES, JobStatus.RUNNING, 30, "Creating scene specifications")
        scenes_data = SceneSpecService().generate(script_data, lesson, page_content)
        if not scenes_data:
            # Fallback from script segments
            scenes_data = []
            for i, seg in enumerate(script_data.get("segments") or []):
                scenes_data.append(
                    {
                        "scene_id": seg.get("scene_id") or f"scene_{i+1:02d}",
                        "order_index": i,
                        "title": seg.get("title") or f"Scene {i+1}",
                        "duration": seg.get("duration_estimate") or 20,
                        "narration": seg.get("narration") or "",
                        "scene_type": seg.get("scene_type") or "custom",
                        "visualization": {
                            "type": seg.get("scene_type") or "concept",
                            "title": seg.get("title"),
                        },
                    }
                )
        scenes_data = sanitize_scenes(scenes_data)

        # Math QC on algebra scenes BEFORE rendering
        math_check = qc.validate_scenes_math(scenes_data)
        if not math_check.ok:
            raise RuntimeError(
                "Mathematical validation failed: " + "; ".join(math_check.messages)
            )

        db.query(Scene).filter(Scene.project_id == project.id).delete()
        db.commit()
        for sc in scenes_data:
            viz = sc.get("visualization") or {}
            stype = _map_scene_type(sc.get("scene_type") or viz.get("type") or "custom")
            db.add(
                Scene(
                    project_id=project.id,
                    scene_id=sc.get("scene_id") or f"scene_{sc.get('order_index', 0):02d}",
                    order_index=int(sc.get("order_index") or 0),
                    scene_type=stype,
                    title=sc.get("title") or "",
                    narration=sc.get("narration") or "",
                    duration_target=float(sc.get("duration") or 20),
                    visualization_spec=viz,
                    status="pending",
                )
            )
        db.commit()
        storage.upload_bytes(
            storage.project_key(project.id, "scenes", "scenes.json"),
            __import__("json").dumps(scenes_data, indent=2).encode(),
            "application/json",
        )
        _set_job(db, project.id, JobStage.SCENES, JobStatus.COMPLETED, 100)

        # --- Voice (narration first) ---
        _set_job(db, project.id, JobStage.VOICE, JobStatus.RUNNING, 10, "Generating narration")
        _update_project(
            db, project, status=ProjectStatus.NARRATION_GENERATED, percent=55, stage="VOICE"
        )
        voice = VoiceService()
        db.query(AudioAsset).filter(AudioAsset.project_id == project.id).delete()
        db.commit()

        scenes = (
            db.query(Scene)
            .filter(Scene.project_id == project.id)
            .order_by(Scene.order_index)
            .all()
        )
        with tempfile.TemporaryDirectory(prefix="mathviz_audio_") as tmp:
            tmp_path = Path(tmp)
            audio_local: dict[str, Path] = {}
            for i, scene in enumerate(scenes):
                pct = 10 + int(80 * (i / max(1, len(scenes))))
                _set_job(
                    db,
                    project.id,
                    JobStage.VOICE,
                    JobStatus.RUNNING,
                    pct,
                    f"Narration {i+1}/{len(scenes)}",
                )
                _update_project(db, project, percent=50 + int(18 * (i / max(1, len(scenes)))), stage="VOICE")
                out = tmp_path / f"{scene.scene_id}.mp3"
                result = voice.synthesize(
                    scene.narration or scene.title or " ",
                    gender=project.voice_gender,
                    speed=project.voice_speed,
                    language=project.language,
                    out_path=out,
                )
                # Narration duration is the scene minimum length
                scene.duration_actual = max(float(scene.duration_target), result.duration_sec)
                key = storage.project_key(project.id, "audio", f"{scene.scene_id}.mp3")
                storage.upload_file(key, str(result.path), "audio/mpeg")
                db.add(
                    AudioAsset(
                        project_id=project.id,
                        scene_id=scene.scene_id,
                        storage_key=key,
                        duration_sec=result.duration_sec,
                        voice=result.voice,
                        format="mp3",
                    )
                )
                audio_local[scene.scene_id] = result.path
                db.commit()

                # Keep a durable local copy for later mux by re-downloading if needed
            _set_job(db, project.id, JobStage.VOICE, JobStatus.COMPLETED, 100)

            # --- MathViz ---
            _set_job(
                db, project.id, JobStage.MATHVIZ, JobStatus.RUNNING, 5, "Creating MathVizAI scenes"
            )
            _update_project(
                db, project, status=ProjectStatus.VISUALIZING, percent=70, stage="MATHVIZ"
            )
            mathviz = MathVizService()
            db.query(VisualizationAsset).filter(
                VisualizationAsset.project_id == project.id
            ).delete()
            db.commit()

            # Download first textbook image for page overview scenes
            textbook_path: Optional[Path] = None
            uploaded_sorted = sorted(
                [u for u in project.uploaded_files if u.processed_storage_key],
                key=lambda u: (u.created_at is None, u.created_at),
            )
            uploaded = uploaded_sorted[0] if uploaded_sorted else None
            if uploaded and uploaded.processed_storage_key:
                textbook_path = tmp_path / "textbook.png"
                storage.download_file(uploaded.processed_storage_key, str(textbook_path))

            viz_local: dict[str, Path] = {}
            for i, scene in enumerate(scenes):
                pct = 5 + int(90 * (i / max(1, len(scenes))))
                _set_job(
                    db,
                    project.id,
                    JobStage.MATHVIZ,
                    JobStatus.RUNNING,
                    pct,
                    f"Visualizing {scene.scene_id}",
                )
                _update_project(
                    db,
                    project,
                    percent=68 + int(20 * (i / max(1, len(scenes)))),
                    stage="MATHVIZ",
                )
                spec = {
                    "scene_id": scene.scene_id,
                    "title": scene.title,
                    "narration": scene.narration,
                    "scene_type": scene.scene_type.value,
                    "visualization": scene.visualization_spec or {"type": scene.scene_type.value},
                }
                scene_dir = tmp_path / f"viz_{scene.scene_id}"
                scene_dir.mkdir(exist_ok=True)
                try:
                    result = mathviz.render_scene(
                        spec,
                        duration_sec=float(scene.duration_actual or scene.duration_target),
                        textbook_image_path=textbook_path,
                        work_dir=scene_dir,
                    )
                    vkey = storage.project_key(project.id, "mathviz", f"{scene.scene_id}.mp4")
                    storage.upload_file(vkey, str(result.video_path), "video/mp4")
                    ckey = storage.project_key(project.id, "mathviz", f"{scene.scene_id}.py")
                    storage.upload_bytes(ckey, result.manim_code.encode("utf-8"), "text/x-python")
                    db.add(
                        VisualizationAsset(
                            project_id=project.id,
                            scene_id=scene.scene_id,
                            storage_key=vkey,
                            manim_code_key=ckey,
                            provider=result.provider,
                            used_fallback=result.used_fallback,
                            duration_sec=result.duration_sec,
                        )
                    )
                    # Copy video to stable path for mux
                    stable = tmp_path / f"{scene.scene_id}_viz.mp4"
                    stable.write_bytes(result.video_path.read_bytes())
                    viz_local[scene.scene_id] = stable
                    scene.status = "visualized"
                except Exception as exc:
                    logger.exception("MathViz failed for %s", scene.scene_id)
                    scene.status = "failed"
                    scene.error_message = str(exc)
                    db.commit()
                    raise RuntimeError(f"MathVizAI failed for {scene.scene_id}: {exc}") from exc
                db.commit()
            _set_job(db, project.id, JobStage.MATHVIZ, JobStatus.COMPLETED, 100)

            # Ensure audio files available (re-download)
            for scene in scenes:
                if scene.scene_id not in audio_local or not audio_local[scene.scene_id].exists():
                    asset = (
                        db.query(AudioAsset)
                        .filter(
                            AudioAsset.project_id == project.id,
                            AudioAsset.scene_id == scene.scene_id,
                        )
                        .first()
                    )
                    if not asset:
                        raise RuntimeError(f"Missing audio for {scene.scene_id}")
                    p = tmp_path / f"{scene.scene_id}.mp3"
                    storage.download_file(asset.storage_key, str(p))
                    audio_local[scene.scene_id] = p

            # --- Render ---
            _set_job(db, project.id, JobStage.RENDER, JobStatus.RUNNING, 10, "Rendering video")
            _update_project(
                db, project, status=ProjectStatus.RENDERING, percent=90, stage="RENDER"
            )
            pairs: list[tuple[Path, Path, float]] = []
            for scene in scenes:
                v = viz_local.get(scene.scene_id)
                a = audio_local.get(scene.scene_id)
                if not v or not a:
                    raise RuntimeError(f"Missing assets for {scene.scene_id}")
                pairs.append((v, a, float(scene.duration_actual or scene.duration_target)))

            renderer = VideoRenderService()
            render_dir = tmp_path / "render"
            assembled = renderer.assemble(pairs, render_dir)

            video_check = qc.validate_video(assembled.path_1080)
            if not video_check.ok:
                raise RuntimeError("Video validation failed: " + "; ".join(video_check.messages))

            db.query(VideoAsset).filter(VideoAsset.project_id == project.id).delete()
            db.commit()
            key_1080 = storage.project_key(project.id, "video", "final_1080p.mp4")
            storage.upload_file(key_1080, str(assembled.path_1080), "video/mp4")
            db.add(
                VideoAsset(
                    project_id=project.id,
                    storage_key=key_1080,
                    resolution="1080p",
                    duration_sec=assembled.duration_sec,
                    file_size_bytes=assembled.path_1080.stat().st_size,
                    is_primary=True,
                    validated=True,
                )
            )
            if assembled.path_720 and assembled.path_720.exists():
                key_720 = storage.project_key(project.id, "video", "final_720p.mp4")
                storage.upload_file(key_720, str(assembled.path_720), "video/mp4")
                db.add(
                    VideoAsset(
                        project_id=project.id,
                        storage_key=key_720,
                        resolution="720p",
                        duration_sec=assembled.duration_sec,
                        file_size_bytes=assembled.path_720.stat().st_size,
                        is_primary=False,
                        validated=True,
                    )
                )
            db.commit()
            _set_job(db, project.id, JobStage.RENDER, JobStatus.COMPLETED, 100)

            # --- Subtitles + finalize ---
            _set_job(db, project.id, JobStage.FINALIZE, JobStatus.RUNNING, 50, "Finalizing")
            _update_project(db, project, percent=97, stage="FINALIZE")
            sub_svc = SubtitleService()
            scene_dicts = [
                {
                    "narration": s.narration,
                    "duration_actual": s.duration_actual,
                    "duration_target": s.duration_target,
                }
                for s in scenes
            ]
            srt, vtt = sub_svc.from_scene_audio(scene_dicts)
            db.query(SubtitleAsset).filter(SubtitleAsset.project_id == project.id).delete()
            db.commit()
            srt_key = storage.project_key(project.id, "subtitles", "lesson.srt")
            vtt_key = storage.project_key(project.id, "subtitles", "lesson.vtt")
            storage.upload_bytes(srt_key, srt.encode("utf-8"), "application/x-subrip")
            storage.upload_bytes(vtt_key, vtt.encode("utf-8"), "text/vtt")
            db.add(SubtitleAsset(project_id=project.id, storage_key=srt_key, format="srt"))
            db.add(SubtitleAsset(project_id=project.id, storage_key=vtt_key, format="vtt"))

            # Lesson markdown export
            md = _lesson_markdown(project, lp, scr, scenes)
            storage.upload_bytes(
                storage.project_key(project.id, "lesson", "lesson.md"),
                md.encode("utf-8"),
                "text/markdown",
            )
            db.commit()

            _set_job(db, project.id, JobStage.FINALIZE, JobStatus.COMPLETED, 100, "Done")
            _update_project(
                db,
                project,
                status=ProjectStatus.COMPLETED,
                percent=100,
                stage="COMPLETED",
                error=None,
            )
            return {
                "project_id": project_id,
                "duration_sec": assembled.duration_sec,
                "scenes": len(scenes),
            }
    except Exception as exc:
        logger.error("Pipeline failed: %s\n%s", exc, traceback.format_exc())
        project = db.get(Project, UUID(project_id))
        if project:
            _update_project(
                db,
                project,
                status=ProjectStatus.FAILED,
                stage=project.progress_stage or "FAILED",
                error=str(exc),
            )
        raise
    finally:
        db.close()


def _lesson_markdown(project: Project, lp: LessonPlan, scr: Script, scenes: list[Scene]) -> str:
    lines = [
        f"# {lp.topic or project.title}",
        "",
        "## Learning objectives",
    ]
    for o in lp.learning_objectives or []:
        lines.append(f"- {o}")
    lines += ["", "## Script", "", scr.full_script or "", "", "## Scenes", ""]
    for s in scenes:
        lines.append(f"### {s.scene_id}: {s.title}")
        lines.append(s.narration or "")
        lines.append("")
    return "\n".join(lines)
