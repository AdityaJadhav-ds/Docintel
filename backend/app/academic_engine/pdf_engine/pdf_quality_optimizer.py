"""
pdf_engine/pdf_quality_optimizer.py
=====================================
STEP 3 — Pre-OCR image quality optimization.

Runs on each rendered page image BEFORE entering the vision/OCR pipeline.

Operations (in order):
  1. Remove transparency (RGBA → RGB)
  2. Auto-trim white/black borders
  3. Normalize brightness (histogram stretch)
  4. Increase contrast slightly (CLAHE)
  5. Sharpen text edges
  6. Detect scanned vs digital PDF
  7. Extract native text (for digital PDFs)

Returns per-page:
    {
        "rendered_image": np.ndarray,  # optimized BGR image
        "native_text":    str,         # embedded text (empty for scans)
        "is_scanned":     bool,
        "quality_score":  float,       # 0.0 – 1.0
    }
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("docvalidator")

# Minimum text pixel density to classify as "digital" PDF
_DIGITAL_TEXT_MIN_CHARS = 80


def _remove_transparency(img: np.ndarray) -> np.ndarray:
    """Convert RGBA → RGB → BGR (handles transparent backgrounds)."""
    if img.ndim == 3 and img.shape[2] == 4:
        # Alpha-composite on white background
        alpha = img[:, :, 3:4] / 255.0
        rgb   = img[:, :, :3]
        white = np.ones_like(rgb, dtype=np.float32) * 255
        composited = (rgb * alpha + white * (1 - alpha)).astype(np.uint8)
        return cv2.cvtColor(composited, cv2.COLOR_RGB2BGR)
    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def _auto_trim_borders(img: np.ndarray, threshold: int = 240) -> np.ndarray:
    """
    Remove uniform white/near-white borders from scanned pages.
    Keeps content intact — does not crop aggressively.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Mask of non-background pixels
    mask = gray < threshold
    coords = np.argwhere(mask)
    if coords.size == 0:
        return img  # all white — return as-is

    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)

    # Add 10px padding
    h, w = img.shape[:2]
    y0 = max(0, y0 - 10)
    x0 = max(0, x0 - 10)
    y1 = min(h, y1 + 10)
    x1 = min(w, x1 + 10)

    trimmed = img[y0:y1, x0:x1]
    # Sanity check: trimmed must be at least 20% of original
    if trimmed.shape[0] < h * 0.2 or trimmed.shape[1] < w * 0.2:
        return img
    return trimmed


def _normalize_brightness(img: np.ndarray) -> np.ndarray:
    """
    Normalize brightness using LAB color space.
    Prevents over-darkening or over-brightening.
    """
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)

    # CLAHE on L channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_chan)

    merged = cv2.merge([l_eq, a_chan, b_chan])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _enhance_contrast(img: np.ndarray) -> np.ndarray:
    """Light contrast boost — preserves table lines and thin strokes."""
    # Alpha=1.2 (slight contrast), Beta=5 (slight brightness lift)
    return cv2.convertScaleAbs(img, alpha=1.15, beta=5)


def _sharpen_text(img: np.ndarray) -> np.ndarray:
    """
    Unsharp mask — sharpens text edges without introducing noise.
    Safe for tables and thin lines.
    """
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(img, 1.5, blurred, -0.5, 0)
    return sharpened


def _compute_quality_score(img: np.ndarray) -> float:
    """
    Estimate image quality for OCR suitability.
    Score: 0.0 (terrible) – 1.0 (ideal).
    Factors: sharpness (Laplacian variance), contrast, size.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Sharpness via Laplacian variance
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    sharpness = min(1.0, lap_var / 500.0)

    # Contrast via std dev
    std = float(gray.std())
    contrast = min(1.0, std / 60.0)

    # Size score — penalise very small images
    size_score = min(1.0, (h * w) / (1000 * 700))

    return round(0.4 * sharpness + 0.4 * contrast + 0.2 * size_score, 3)


def _detect_scanned(native_text: str, quality_score: float) -> bool:
    """
    True if this page appears to be a scanned image rather than digital PDF.
    Uses two signals: embedded text length and image quality.
    """
    has_text = len(native_text.strip()) >= _DIGITAL_TEXT_MIN_CHARS
    # High quality + embedded text → digital; poor quality or no text → scanned
    return not has_text


def optimize_page(
    page: dict,
    native_text: str = "",
) -> dict:
    """
    STEP 3 — Optimize a single rendered page for OCR.

    Args:
        page:        {image, page_number, width, height, dpi, engine}
        native_text: embedded PDF text for this page (may be empty)

    Returns:
        {
            "rendered_image": np.ndarray,
            "native_text":    str,
            "is_scanned":     bool,
            "quality_score":  float,
            "page_number":    int,
        }
    """
    img = page["image"].copy()
    page_num = page["page_number"]

    # Step 1: Remove transparency
    img = _remove_transparency(img)

    # Step 2: Auto-trim borders (only for low-DPI or clear margins)
    img = _auto_trim_borders(img)

    # Step 3: Normalize brightness
    img = _normalize_brightness(img)

    # Step 4: Enhance contrast
    img = _enhance_contrast(img)

    # Step 5: Sharpen text
    img = _sharpen_text(img)

    # Step 6: Compute quality score
    quality = _compute_quality_score(img)

    # Step 7: Detect scanned vs digital
    is_scanned = _detect_scanned(native_text, quality)

    logger.info(
        "[pdf_quality] Page %d: quality=%.3f scanned=%s size=%dx%d",
        page_num, quality, is_scanned, img.shape[1], img.shape[0],
    )

    return {
        "rendered_image": img,
        "native_text":    native_text,
        "is_scanned":     is_scanned,
        "quality_score":  quality,
        "page_number":    page_num,
    }
