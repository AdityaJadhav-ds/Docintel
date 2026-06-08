"""
app/extraction/pdf.py
======================
PDF / image → List[np.ndarray] renderer.

ONE renderer. ONE DPI. ONE resize limit.
No fallbacks. No multiple engines.

Uses PyMuPDF (fitz) only.
"""
from __future__ import annotations

import base64
import logging
from typing import List

import cv2
import numpy as np

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # Will raise clearly at runtime

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# 1.8x scale ≈ 170 DPI — fast and sharp enough for PaddleOCR
_DPI_MATRIX = None  # initialized lazily (fitz may not be imported yet)
MAX_WIDTH = 1800     # px — resize before OCR for speed


def _get_matrix():
    global _DPI_MATRIX
    if _DPI_MATRIX is None:
        _DPI_MATRIX = fitz.Matrix(1.8, 1.8)
    return _DPI_MATRIX


# ── Public API ────────────────────────────────────────────────────────────────

def render_pages(file_bytes: bytes, filename: str) -> List[np.ndarray]:
    """
    Convert any supported document to a list of BGR images (one per page).

    Supported inputs:
      - PDF  → rendered via PyMuPDF at ~170 DPI, resized to MAX_WIDTH
      - JPG / PNG / BMP → loaded directly, resized to MAX_WIDTH
    """
    name_lower = (filename or "").lower()
    if name_lower.endswith(".pdf"):
        return _render_pdf(file_bytes)
    else:
        return _load_image(file_bytes)


def image_to_b64(bgr: np.ndarray) -> str:
    """Encode a BGR image to a base64 JPEG string (data: URI) for frontend."""
    try:
        h, w = bgr.shape[:2]
        # Scale down preview to max 1200px wide — frontend doesn't need more
        if w > 1200:
            scale = 1200 / w
            bgr = cv2.resize(bgr, (1200, int(h * scale)), interpolation=cv2.INTER_AREA)
        _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    except Exception as e:
        logger.warning("[pdf] image_to_b64 failed: %s", e)
        return ""


# ── Internal ──────────────────────────────────────────────────────────────────

def _render_pdf(file_bytes: bytes) -> List[np.ndarray]:
    """Render each PDF page to a BGR numpy array."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is not installed. Run: pip install pymupdf")

    matrix = _get_matrix()
    pages: List[np.ndarray] = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF: {e}") from e

    try:
        for page_idx, page in enumerate(doc):
            try:
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
                # RGB → BGR for OpenCV
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                img = _resize(img)
                pages.append(img)
                logger.debug("[pdf] Page %d rendered: %dx%d", page_idx, img.shape[1], img.shape[0])
            except Exception as e:
                logger.error("[pdf] Failed to render page %d: %s", page_idx, e)
                # Append a blank page so page count stays consistent
                pages.append(np.zeros((1200, 900, 3), dtype=np.uint8))
    finally:
        doc.close()

    if not pages:
        raise RuntimeError("PDF rendered zero pages")

    return pages


def _load_image(file_bytes: bytes) -> List[np.ndarray]:
    """Load a JPG/PNG image file as a single-page list."""
    arr = np.frombuffer(file_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Failed to decode image file — unsupported format or corrupt data")
    img = _resize(img)
    return [img]


def _resize(img: np.ndarray) -> np.ndarray:
    """Resize image so width ≤ MAX_WIDTH. Preserves aspect ratio."""
    h, w = img.shape[:2]
    if w > MAX_WIDTH:
        new_w = MAX_WIDTH
        new_h = int(h * MAX_WIDTH / w)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return img
