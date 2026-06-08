"""
academic_engine/scanner/background_cleaner.py
=============================================
STEP 5 — Background Normalisation & Watermark Suppression.

Normalises the paper to a clean white background:
  • Remove grey tint / yellow ageing from paper
  • Suppress faint watermarks / security patterns
  • Bring paper white to RGB(255,255,255)
  • Boost contrast of printed text

Also handles:
STEP 6 — WhatsApp / JPEG Artefact Cleanup
  • Deblocking (bilateral filter)
  • Non-local means denoising (NLM)
  • Ringing artefact suppression
"""

from __future__ import annotations

import cv2
import numpy as np
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

# Percentile of the brightness histogram considered "paper white"
PAPER_WHITE_PERCENTILE = 97

# Gamma correction for paper whitening  (< 1 = brighten)
GAMMA_BRIGHT  = 0.85

# NLM denoising parameters
NLM_H            = 6    # filter strength (luminance)
NLM_H_COLOR      = 4    # filter strength (colour)
NLM_TEMPLATE_WIN = 7
NLM_SEARCH_WIN   = 21

# Bilateral deblocking
DEBLOCK_D           = 7
DEBLOCK_SIGMA_COLOR = 50
DEBLOCK_SIGMA_SPACE = 50

# Sharpening kernel for mild crispening after denoise
UNSHARP_SIGMA  = 1.0
UNSHARP_AMOUNT = 0.6    # blend fraction


# ── Paper whitening ───────────────────────────────────────────────────────────

def _gamma_correction(image: np.ndarray, gamma: float) -> np.ndarray:
    """Apply per-channel gamma correction (LUT-based for speed)."""
    inv_gamma = 1.0 / gamma
    table = np.array(
        [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(image, table)


def _stretch_to_white(image: np.ndarray) -> np.ndarray:
    """
    Per-channel histogram stretch:
      • Find the Nth-percentile bright value in each channel.
      • Scale so that value becomes 255.
    This removes overall grey/yellow tint and maps paper white → 255.
    """
    result = image.astype(np.float32)
    for ch in range(result.shape[2]):
        channel = result[:, :, ch]
        p_high  = float(np.percentile(channel, PAPER_WHITE_PERCENTILE))
        if p_high < 10:
            continue
        result[:, :, ch] = np.clip(channel / p_high * 255.0, 0, 255)
    return result.astype(np.uint8)


def _suppress_watermark(gray: np.ndarray) -> np.ndarray:
    """
    Suppress light watermarks using a large-radius mean blur baseline.
    Very faint features (watermark) are blurred out; text remains because
    text is high-frequency and restored via unsharp mask later.

    NOTE: This only mutes *very* faint (< 30 grey-level) patterns.
    Heavy watermarks require dedicated frequency-domain removal (out of scope).
    """
    blur = cv2.GaussianBlur(gray, (31, 31), 0)
    diff = gray.astype(np.int16) - blur.astype(np.int16)
    # Keep only features darker than background by > 30 grey levels
    mask = (diff < -30).astype(np.uint8) * 255
    result = gray.copy()
    # Where the diff is small (watermark territory), push toward white
    light_region = diff > -15
    result[light_region] = np.clip(
        result[light_region].astype(np.int16) + 15, 0, 255
    ).astype(np.uint8)
    return result


def normalise_background(image: np.ndarray) -> np.ndarray:
    """
    Make paper background clean white:
      1. Histogram stretch (per-channel) to remove grey/yellow tint.
      2. Gamma brightening for overall lift.
      3. Watermark suppression on luminance.

    Args:
        image: BGR numpy array

    Returns:
        Background-normalised BGR numpy array
    """
    if image is None or image.size == 0:
        return image

    h, w = image.shape[:2]
    logger.info("[background_cleaner] normalise_background %dx%d", w, h)

    # 1. Histogram stretch
    stretched = _stretch_to_white(image)

    # 2. Mild gamma brightening
    brightened = _gamma_correction(stretched, GAMMA_BRIGHT)

    # 3. Watermark suppression on grey
    lab = cv2.cvtColor(brightened, cv2.COLOR_BGR2LAB)
    L, A, B = cv2.split(lab)
    L = _suppress_watermark(L)
    lab = cv2.merge([L, A, B])
    result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    logger.info("[background_cleaner] Background normalised")
    return result


# ── WhatsApp / JPEG artefact cleanup ─────────────────────────────────────────

def remove_compression_artefacts(image: np.ndarray) -> np.ndarray:
    """
    STEP 6: Remove JPEG / WhatsApp compression artefacts:
      1. Bilateral deblocking filter (edges preserved, block artefacts blurred)
      2. Non-local means denoising (NLM) for ringing & mosquito noise
      3. Mild unsharp mask to restore edge crispness without oversharpening

    Args:
        image: BGR numpy array (possibly WhatsApp-compressed)

    Returns:
        Cleaned BGR numpy array
    """
    if image is None or image.size == 0:
        return image

    h, w = image.shape[:2]
    logger.info("[background_cleaner] remove_compression_artefacts %dx%d", w, h)

    # Step 1: Bilateral deblocking
    deblocked = cv2.bilateralFilter(
        image,
        DEBLOCK_D,
        DEBLOCK_SIGMA_COLOR,
        DEBLOCK_SIGMA_SPACE,
    )

    # Step 2: Non-local means denoising
    denoised = cv2.fastNlMeansDenoisingColored(
        deblocked,
        None,
        h=NLM_H,
        hColor=NLM_H_COLOR,
        templateWindowSize=NLM_TEMPLATE_WIN,
        searchWindowSize=NLM_SEARCH_WIN,
    )

    # Step 3: Unsharp mask — blend original sharpness back lightly
    blur   = cv2.GaussianBlur(denoised, (0, 0), UNSHARP_SIGMA)
    result = cv2.addWeighted(denoised, 1.0 + UNSHARP_AMOUNT, blur, -UNSHARP_AMOUNT, 0)

    logger.info("[background_cleaner] Artefact removal complete")
    return result


def clean_background(image: np.ndarray) -> np.ndarray:
    """
    Full background pipeline: normalise then remove compression artefacts.
    """
    step1 = normalise_background(image)
    step2 = remove_compression_artefacts(step1)
    return step2
