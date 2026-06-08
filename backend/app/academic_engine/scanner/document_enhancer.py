"""
academic_engine/scanner/document_enhancer.py
============================================
STEP 8 — Text Sharpening & Final Enhancement.

Sharpens:
  • Thin / fine text strokes
  • Faded / low-contrast print
  • OCR-critical character edges

WITHOUT oversharpening (no halo artefacts, no noise amplification).

Techniques:
  1. Unsharp Mask (controlled σ + amount)
  2. CLAHE on L-channel (local contrast)
  3. Adaptive thresholding overlay option (text-only boost)
  4. Final contrast stretch to push text to near-black
"""

from __future__ import annotations

import cv2
import numpy as np
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

# Unsharp mask parameters (for text sharpening)
USM_SIGMA    = 1.5    # Gaussian sigma — controls spatial extent
USM_AMOUNT   = 0.8    # Blend factor — how much sharpening to mix in
USM_THRESHOLD = 3     # Only sharpen pixels where difference > this (0-255)

# CLAHE for local contrast boost
CLAHE_CLIP   = 3.0
CLAHE_TILE   = (8, 8)

# Final tone-curve parameters
DARK_POINT   = 30     # grey values below this → black
BRIGHT_POINT = 230    # grey values above this → white


# ── Algorithms ────────────────────────────────────────────────────────────────

def _unsharp_mask(image: np.ndarray, sigma: float, amount: float, threshold: int) -> np.ndarray:
    """
    Unsharp mask with threshold to prevent noise amplification.
    Only sharpens pixels where |original - blurred| > threshold.
    """
    blurred = cv2.GaussianBlur(image, (0, 0), sigma)
    diff    = image.astype(np.int16) - blurred.astype(np.int16)

    # Apply threshold: ignore small differences (noise)
    mask = np.abs(diff) > threshold

    sharpened = image.astype(np.float32) + amount * diff.astype(np.float32) * mask
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def _clahe_enhance(image: np.ndarray) -> np.ndarray:
    """
    CLAHE in LAB colour space to boost local contrast without colour shift.
    """
    lab     = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    clahe   = cv2.createCLAHE(clipLimit=CLAHE_CLIP, tileGridSize=CLAHE_TILE)
    L       = clahe.apply(L)
    lab     = cv2.merge([L, A, B])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _tone_curve_stretch(image: np.ndarray, dark: int, bright: int) -> np.ndarray:
    """
    Linear tone curve:
      • Everything ≤ dark  → 0   (push darks to black)
      • Everything ≥ bright → 255 (push brights to white)
      • Linear interpolation between.
    Boosts text-to-background contrast.
    """
    table = np.zeros(256, dtype=np.uint8)
    for i in range(256):
        if i <= dark:
            table[i] = 0
        elif i >= bright:
            table[i] = 255
        else:
            table[i] = int((i - dark) / (bright - dark) * 255)
    return cv2.LUT(image, table)


def _adaptive_text_boost(gray: np.ndarray) -> np.ndarray:
    """
    Adaptive threshold overlay:
    Generate a binary mask of text via Gaussian adaptive threshold,
    then blend it lightly into the image to reinforce thin strokes.
    Returns enhanced grayscale.
    """
    adaptive = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=4,
    )
    # Blend: mostly original + 20% adaptive binary to darken text regions
    blended = cv2.addWeighted(gray, 0.85, adaptive, 0.15, 0)
    return blended


# ── Public API ────────────────────────────────────────────────────────────────

def enhance_document(image: np.ndarray, aggressive: bool = False) -> np.ndarray:
    """
    Apply final text-sharpening and enhancement pipeline.

    Args:
        image     : BGR numpy array (post shadow-removal / bg-normalisation)
        aggressive: If True, applies a stronger CLAHE + tone stretch.
                    Use for very faded / low-quality documents.

    Returns:
        Enhanced BGR numpy array ready for OCR.
    """
    if image is None or image.size == 0:
        logger.warning("[document_enhancer] Empty image")
        return image

    h, w = image.shape[:2]
    logger.info("[document_enhancer] Enhancing %dx%d (aggressive=%s)", w, h, aggressive)

    # 1. CLAHE local contrast
    result = _clahe_enhance(image)

    # 2. Unsharp mask for text edge crispening
    result = _unsharp_mask(result, USM_SIGMA, USM_AMOUNT, USM_THRESHOLD)

    # 3. Tone curve to push text toward black and background toward white
    dark   = DARK_POINT  if not aggressive else max(0,   DARK_POINT   - 10)
    bright = BRIGHT_POINT if not aggressive else min(255, BRIGHT_POINT + 10)
    result = _tone_curve_stretch(result, dark, bright)

    # 4. Mild adaptive text boost for faded text (in LAB L-channel)
    if aggressive:
        lab     = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)
        L, A, B = cv2.split(lab)
        L       = _adaptive_text_boost(L)
        lab     = cv2.merge([L, A, B])
        result  = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    logger.info("[document_enhancer] Enhancement complete")
    return result
