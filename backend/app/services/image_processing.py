"""Image / PDF preprocessing for textbook page uploads."""

from __future__ import annotations

import io
from typing import Optional

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image, ImageOps

from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "application/pdf",
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # WEBP starts with RIFF....WEBP
    b"%PDF": "application/pdf",
}


def detect_content_type(data: bytes, declared: str, filename: str) -> str:
    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise ValueError(f"Unsupported file extension for {filename}")

    detected: Optional[str] = None
    for magic, ctype in MAGIC_SIGNATURES.items():
        if data.startswith(magic):
            if ctype == "image/webp":
                if b"WEBP" in data[:16]:
                    detected = ctype
            else:
                detected = ctype
            break

    if detected is None:
        raise ValueError("Could not verify file type from content (magic bytes)")

    # Normalize jpg
    if declared in ("image/jpg", "image/jpeg") and detected == "image/jpeg":
        return "image/jpeg"
    if declared and declared != detected and not (
        declared in ("image/jpg", "image/jpeg") and detected == "image/jpeg"
    ):
        logger.warning("Declared type %s differs from detected %s", declared, detected)
    return detected


def pdf_page_to_png(data: bytes, page_number: int = 1, dpi: int = 200) -> bytes:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if page_number < 1 or page_number > len(doc):
            raise ValueError(f"PDF has {len(doc)} page(s); requested page {page_number}")
        page = doc[page_number - 1]
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def to_pil(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    return img


def apply_transform(
    data: bytes,
    *,
    rotation: int = 0,
    crop: Optional[dict] = None,
) -> tuple[bytes, int, int]:
    """Apply rotation (degrees CW) and optional crop box in normalized 0-1 coords."""
    img = to_pil(data)
    if rotation:
        # PIL rotates counter-clockwise; convert CW to CCW
        img = img.rotate(-rotation, expand=True)

    if crop:
        w, h = img.size
        left = int(max(0, min(1, crop["x"])) * w)
        top = int(max(0, min(1, crop["y"])) * h)
        right = int(max(0, min(1, crop["x"] + crop["width"])) * w)
        bottom = int(max(0, min(1, crop["y"] + crop["height"])) * h)
        if right - left < 10 or bottom - top < 10:
            raise ValueError("Crop region is too small")
        img = img.crop((left, top, right, bottom))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.width, img.height


def preprocess_for_ocr(data: bytes) -> bytes:
    """Deskew / denoise lightly while preserving math symbols."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image for OCR preprocessing")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Mild denoise
    denoised = cv2.fastNlMeansDenoising(gray, None, h=8, templateWindowSize=7, searchWindowSize=21)
    # Adaptive threshold for contrast (keep as RGB for vision models)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)

    # Deskew using moments of binary edges
    edges = cv2.Canny(enhanced, 50, 150)
    coords = np.column_stack(np.where(edges > 0))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) < 15 and abs(angle) > 0.3:
            (h, w) = enhanced.shape
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            enhanced = cv2.warpAffine(
                enhanced, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            img = cv2.warpAffine(
                img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )

    # Blend enhanced luminance back into color image for vision OCR
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    ycrcb[:, :, 0] = enhanced
    out = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
    ok, encoded = cv2.imencode(".png", out)
    if not ok:
        raise ValueError("Failed to encode preprocessed image")
    return encoded.tobytes()


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
