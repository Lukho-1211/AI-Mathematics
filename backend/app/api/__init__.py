from app.api.projects import router as projects_router
from app.api.upload_ocr import router as upload_ocr_router
from app.api.video_progress import router as video_progress_router

__all__ = ["projects_router", "upload_ocr_router", "video_progress_router"]
