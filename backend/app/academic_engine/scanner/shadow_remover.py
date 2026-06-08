"""
academic_engine/scanner/shadow_remover.py
=========================================
STEP 4 — Shadow Removal & Illumination Normalisation.

Removes:
  • Hand / finger shadows
  • Corner vignetting / dark borders
  • Gradient lighting across the page
  • Uneven flash illumination

Techniques:
  1. Morphological background estimation  (large-kernel dilation)
  2. Division normalisation               (image / background → flat field)
  3. CLAHE on luminance channel           (local contrast equalisation)
  4. Bilateral lighting correction        (edge-preserving smooth + divide)

All operations are performed in float32 for precision and converted back to uint8.
"""

from __future__ import annotations

import cv2
import numpy as np
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

# Morphological kernel size for background estimation.
# Large = captures macro illumination gradients.
BG_KERNEL_SIZE = 71   # must be odd

# CLAHE parameters applied after division normalisation
CLAHE_CLIP      = 2.0
CLAHE_TILE      = (8, 8)

# Bilateral filter settings for fine shadow smoothing
BILATERAL_D    = 9
BILATERAL_SIGMA_COLOR  = 75
BILATERAL_SIGMA_SPACE  = 75


# ── Core algorithms ───────────────────────────────────────────────────────────

def _morphological_background(gray: np.ndarray) -> np.ndarray:
    """
    Estimate the illumination background using morphological dilation.
    Dilating with a large kernel fills dark text pixels with the surrounding
    bright background value → gives a smooth "background" image.
    """
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (BG_KERNEL_SIZE, BG_KERNEL_SIZE)
    )
    bg = cv2.dilate(gray, kernel)
    # Smooth the estimated background
    bg = cv2.GaussianBlur(bg, (BG_KERNEL_SIZE, BG_KERNEL_SIZE), 0)
    return bg


def _divide_normalise(gray: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """
    Divide-normalise: pixel = (pixel / background) * 255.
    This cancels the illumination gradient and leaves only document content.
    """
    gray_f = gray.astype(np.float32)
    bg_f   = bg.astype(np.float32)
    bg_f   = np.where(bg_f < 1.0, 1.0, bg_f)  # avoid division by zero
    result = (gray_f / bg_f) * 255.0
    result = np.clip(result, 0, 255).astype(np.uint8)
    return result


def _apply_clahe(gray: np.ndarray) -> np.ndarray:
    """Apply CLAHE to enhance local contrast after division normalisation."""
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_TILE)
    return clahe.apply(gray)


def _remove_shadow_single_channel(gray: np.ndarray) -> np.ndarray:
    """
    Full shadow removal pipeline for a single-channel (grayscale) image.
    Returns a normalised uint8 grayscale image.
    """
    # 1. Estimate background illumination
    bg = _morphological_background(gray)

    # 2. Division normalise
    normalised = _divide_normalise(gray, bg)

    # 3. CLAHE for local contrast
    enhanced = _apply_clahe(normalised)

    return enhanced


def remove_shadows(image: np.ndarray) -> np.ndarray:
    """
    Remove shadows and normalise illumination from a BGR image.

    Strategy for colour images:
      • Convert to LAB colour space
      • Apply shadow removal only to the L (luminance) channel
      • Merge back and convert to BGR
      This preserves hue/saturation so printed colours remain accurate.

    Args:
        image: BGR numpy array (H×W×3, uint8)

    Returns:
        Shadow-removed BGR numpy array (same size, uint8)
    """
    if image is None or image.size == 0:
        logger.warning("[shadow_remover] Empty image received")
        return image

    h, w = image.shape[:2]
    logger.info("[shadow_remover] Processing %dx%d image", w, h)

    try:
        # Convert to LAB
        lab   = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        L, A, B = cv2.split(lab)

        # Remove shadows from L channel only
        L_clean = _remove_shadow_single_channel(L)

        # Optional bilateral smoothing on L to blend any remaining gradient
        L_smooth = cv2.bilateralFilter(
            L_clean,
            BILATERAL_D,
            BILATERAL_SIGMA_COLOR,
            BILATERAL_SIGMA_SPACE,
        )

        # Merge and convert back
        lab_clean = cv2.merge([L_smooth, A, B])
        result    = cv2.cvtColor(lab_clean, cv2.COLOR_LAB2BGR)

        logger.info("[shadow_remover] Shadow removal complete")
        return result

    except Exception as exc:
        logger.error("[shadow_remover] Failed: %s — returning original", exc)
        return image


def estimate_shadow_severity(image: np.ndarray) -> float:
    """
    Estimate shadow severity as a float 0.0 (no shadow) – 1.0 (heavy shadow).

    Method: compute the standard deviation of the low-frequency illumination
    map (morphological background).  High σ = strong illumination gradient.
    """
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        bg   = _morphological_background(gray)
        std  = float(np.std(bg.astype(np.float32)))
        # Normalise: σ ≈ 0 → no gradient; σ ≈ 60+ → severe gradient
        severity = float(np.clip(std / 60.0, 0.0, 1.0))
        return severity
    except Exception:
        return 0.0
