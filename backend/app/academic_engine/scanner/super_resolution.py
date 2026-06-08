"""
academic_engine/scanner/super_resolution.py
===========================================
STEP 7 — Super Resolution / Upscaling.

Upscales low-quality / low-DPI document images to ≥ 300 DPI equivalent.

Strategy (in priority order):
  1. OpenCV DNN Super Resolution (EDSR / ESPCN / FSRCNN / LapSRN)
     — Loads pre-trained ONNX / pb models from SR_MODELS_DIR if available.
  2. Lanczos interpolation upscale × 2 or × 3
     — Always available, decent quality for text documents.

Target output: at least TARGET_MIN_LONG_EDGE pixels on the long side.
If the image is already large enough, the function is a no-op.
"""

from __future__ import annotations

import math
import os
import cv2
import numpy as np
from pathlib import Path
from typing import Tuple
from app.core.logger import logger


# ── Configuration ─────────────────────────────────────────────────────────────

TARGET_MIN_LONG_EDGE = 2000    # pixels — corresponds to ~300 DPI for A4
MAX_UPSCALE_FACTOR   = 4       # never upscale more than 4×

# Directory where pre-trained SR model files live (optional)
# Models: EDSR_x2.pb, EDSR_x3.pb, EDSR_x4.pb (OpenCV contrib)
SR_MODELS_DIR = Path(
    os.environ.get(
        "SR_MODELS_DIR",
        str(Path(__file__).resolve().parent.parent.parent.parent / "models" / "sr"),
    )
)

# Model configs: (algorithm_name, scale, model_filename)
SR_MODEL_CONFIGS = [
    ("edsr",   4, "EDSR_x4.pb"),
    ("edsr",   3, "EDSR_x3.pb"),
    ("edsr",   2, "EDSR_x2.pb"),
    ("espcn",  4, "ESPCN_x4.pb"),
    ("espcn",  3, "ESPCN_x3.pb"),
    ("fsrcnn", 4, "FSRCNN_x4.pb"),
]


# ── DNN super resolution ──────────────────────────────────────────────────────

def _try_dnn_sr(image: np.ndarray, target_scale: int) -> Tuple[np.ndarray, bool]:
    """
    Attempt upscaling using OpenCV's DNN super-resolution module.
    Returns (upscaled_image, success).
    """
    try:
        # Check if dnn_superres is available (requires opencv-contrib-python)
        from cv2 import dnn_superres   # type: ignore
    except ImportError:
        logger.debug("[super_resolution] cv2.dnn_superres not available (needs opencv-contrib-python)")
        return image, False

    for algo, scale, filename in SR_MODEL_CONFIGS:
        if scale != target_scale:
            continue
        model_path = SR_MODELS_DIR / filename
        if not model_path.exists():
            logger.debug("[super_resolution] Model not found: %s", model_path)
            continue
        try:
            sr = dnn_superres.DnnSuperResImpl_create()
            sr.readModel(str(model_path))
            sr.setModel(algo, scale)
            upscaled = sr.upsample(image)
            logger.info(
                "[super_resolution] DNN SR (%s ×%d): %dx%d → %dx%d",
                algo.upper(), scale,
                image.shape[1], image.shape[0],
                upscaled.shape[1], upscaled.shape[0],
            )
            return upscaled, True
        except Exception as exc:
            logger.warning("[super_resolution] DNN SR %s ×%d failed: %s", algo, scale, exc)

    return image, False


# ── Lanczos interpolation ─────────────────────────────────────────────────────

def _lanczos_upscale(image: np.ndarray, scale: float) -> np.ndarray:
    """Upscale using LANCZOS4 interpolation (best quality for text)."""
    h, w  = image.shape[:2]
    new_w = int(w * scale)
    new_h = int(h * scale)
    result = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    logger.info(
        "[super_resolution] Lanczos ×%.2f: %dx%d → %dx%d",
        scale, w, h, new_w, new_h,
    )
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def upscale_document(image: np.ndarray) -> np.ndarray:
    """
    Upscale *image* to at least TARGET_MIN_LONG_EDGE pixels on its long side.
    No-op if image is already large enough.

    Priority:
      1. OpenCV DNN super-resolution (if model files present)
      2. Lanczos ×2 / ×3 / ×4 interpolation

    Args:
        image: BGR numpy array

    Returns:
        Upscaled BGR numpy array (or original if no upscaling needed)
    """
    if image is None or image.size == 0:
        return image

    h, w       = image.shape[:2]
    long_edge  = max(h, w)
    logger.info("[super_resolution] Input: %dx%d (long edge=%d)", w, h, long_edge)

    if long_edge >= TARGET_MIN_LONG_EDGE:
        logger.info("[super_resolution] No upscaling needed (already %d px)", long_edge)
        return image

    # Determine minimum integer scale factor needed
    needed_scale = math.ceil(TARGET_MIN_LONG_EDGE / long_edge)
    scale        = min(needed_scale, MAX_UPSCALE_FACTOR)
    logger.info("[super_resolution] Target scale: ×%d", scale)

    # Try DNN SR first
    upscaled, success = _try_dnn_sr(image, scale)
    if success:
        return upscaled

    # Lanczos fallback
    upscaled = _lanczos_upscale(image, float(scale))
    return upscaled
