"""
app/fraud/quality_analyzer.py — Document image quality intelligence
====================================================================
Measures 7 quality signals using pure OpenCV + NumPy:
  1. Blur (Laplacian variance)
  2. Brightness (mean luminance)
  3. Contrast (std of luminance)
  4. Noise level (high-freq component)
  5. Edge density (Canny edge fraction)
  6. Shannon entropy (information density)
  7. Text region readability (estimated)

Produces:
  quality_score: 0-100
  blur_class: sharp | acceptable | blurry | unusable
  quality_flags: list of detected issues
"""

from __future__ import annotations
import math
import io
from typing import Dict, List, Tuple, Optional
import numpy as np
import cv2
from PIL import Image
from app.core.logger import logger


# ── Constants & thresholds ────────────────────────────────────────────────────

class BlurClass:
    SHARP      = "sharp"
    ACCEPTABLE = "acceptable"
    BLURRY     = "blurry"
    UNUSABLE   = "unusable"

BLUR_THRESHOLDS = {
    BlurClass.SHARP:      200,   # Laplacian variance
    BlurClass.ACCEPTABLE: 80,
    BlurClass.BLURRY:     30,
}

BRIGHTNESS_MIN    = 40     # 0-255
BRIGHTNESS_MAX    = 220
CONTRAST_MIN      = 20     # std dev
NOISE_MAX_RATIO   = 0.12   # fraction of energy
EDGE_MIN_DENSITY  = 0.03   # fraction of edge pixels
ENTROPY_MIN       = 5.5    # bits


# ── Image loader ──────────────────────────────────────────────────────────────

def _load_gray(image_input) -> Optional[np.ndarray]:
    """Load image input as uint8 grayscale numpy array."""
    try:
        if isinstance(image_input, np.ndarray):
            if image_input.ndim == 3:
                return cv2.cvtColor(image_input, cv2.COLOR_BGR2GRAY)
            return image_input
        if isinstance(image_input, Image.Image):
            return np.array(image_input.convert("L"))
        if hasattr(image_input, "read"):
            pos = image_input.tell()
            data = image_input.read()
            image_input.seek(pos)
            arr = np.frombuffer(data, np.uint8)
        elif isinstance(image_input, bytes):
            arr = np.frombuffer(image_input, np.uint8)
        else:
            return cv2.imread(str(image_input), cv2.IMREAD_GRAYSCALE)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        return img
    except Exception as exc:
        logger.error("[quality_analyzer] load_gray error: %s", exc)
        return None


def _load_bgr(image_input) -> Optional[np.ndarray]:
    """Load image as BGR array."""
    try:
        if isinstance(image_input, np.ndarray):
            if image_input.ndim == 2:
                return cv2.cvtColor(image_input, cv2.COLOR_GRAY2BGR)
            return image_input
        if isinstance(image_input, Image.Image):
            return cv2.cvtColor(np.array(image_input.convert("RGB")), cv2.COLOR_RGB2BGR)
        if hasattr(image_input, "read"):
            pos  = image_input.tell()
            data = image_input.read()
            image_input.seek(pos)
            arr  = np.frombuffer(data, np.uint8)
        elif isinstance(image_input, bytes):
            arr = np.frombuffer(image_input, np.uint8)
        else:
            return cv2.imread(str(image_input))
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as exc:
        logger.error("[quality_analyzer] load_bgr error: %s", exc)
        return None


# ── Signal detectors ──────────────────────────────────────────────────────────

def _measure_blur(gray: np.ndarray) -> Tuple[float, str]:
    """Laplacian variance: higher = sharper. Returns (variance, blur_class)."""
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if lap_var >= BLUR_THRESHOLDS[BlurClass.SHARP]:
        return lap_var, BlurClass.SHARP
    if lap_var >= BLUR_THRESHOLDS[BlurClass.ACCEPTABLE]:
        return lap_var, BlurClass.ACCEPTABLE
    if lap_var >= BLUR_THRESHOLDS[BlurClass.BLURRY]:
        return lap_var, BlurClass.BLURRY
    return lap_var, BlurClass.UNUSABLE


def _measure_brightness(gray: np.ndarray) -> Tuple[float, str]:
    """Mean luminance. Returns (mean, 'dark'|'ok'|'overexposed')."""
    mean = float(gray.mean())
    if mean < BRIGHTNESS_MIN:
        return mean, "dark"
    if mean > BRIGHTNESS_MAX:
        return mean, "overexposed"
    return mean, "ok"


def _measure_contrast(gray: np.ndarray) -> Tuple[float, str]:
    """Std dev of pixel values as contrast proxy."""
    std = float(gray.std())
    status = "low_contrast" if std < CONTRAST_MIN else "ok"
    return std, status


def _measure_noise(gray: np.ndarray) -> Tuple[float, str]:
    """
    Estimate noise via high-frequency component.
    Apply strong Gaussian blur and compare energy.
    """
    blurred   = cv2.GaussianBlur(gray, (15, 15), 0).astype(float)
    hf        = gray.astype(float) - blurred
    total_e   = float(np.sum(gray.astype(float) ** 2)) + 1e-6
    noise_e   = float(np.sum(hf ** 2))
    ratio     = noise_e / total_e
    status    = "high_noise" if ratio > NOISE_MAX_RATIO else "ok"
    return round(ratio, 4), status


def _measure_edge_density(gray: np.ndarray) -> Tuple[float, str]:
    """Canny edge fraction. Low = may be blank/cropped/too dark."""
    edges   = cv2.Canny(gray, 50, 150)
    density = float(np.count_nonzero(edges)) / edges.size
    status  = "low_edge_density" if density < EDGE_MIN_DENSITY else "ok"
    return round(density, 4), status


def _measure_entropy(gray: np.ndarray) -> Tuple[float, str]:
    """Shannon entropy of histogram. Low = flat/compressed image."""
    hist  = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    hist  = hist / hist.sum()
    ent   = float(-np.sum(hist[hist > 0] * np.log2(hist[hist > 0])))
    status = "low_entropy" if ent < ENTROPY_MIN else "ok"
    return round(ent, 3), status


def _measure_resolution(gray: np.ndarray) -> Tuple[int, int, str]:
    """Resolution check. Small images likely mobile screenshots or crops."""
    h, w = gray.shape[:2]
    if w < 300 or h < 150:
        return w, h, "very_low_resolution"
    if w < 600 or h < 300:
        return w, h, "low_resolution"
    return w, h, "ok"


def _measure_glare(gray: np.ndarray) -> Tuple[bool, str]:
    """Detect overexposed specular regions (glare/flash)."""
    _, thresh = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY)
    glare_frac = float(np.count_nonzero(thresh)) / thresh.size
    if glare_frac > 0.05:
        return True, "glare_detected"
    return False, "ok"


# ── Quality score combiner ────────────────────────────────────────────────────

def _compute_quality_score(
    blur_var:      float,
    blur_class:    str,
    brightness:    float,
    brightness_st: str,
    contrast:      float,
    contrast_st:   str,
    noise:         float,
    noise_st:      str,
    edge_density:  float,
    edge_st:       str,
    entropy:       float,
    entropy_st:    str,
    width:         int,
    height:        int,
    res_st:        str,
    glare:         bool,
) -> int:
    """Weighted combination of all quality signals → 0-100."""
    score = 100

    # Blur penalty (heaviest weight)
    blur_penalties = {
        BlurClass.SHARP:      0,
        BlurClass.ACCEPTABLE: 10,
        BlurClass.BLURRY:     35,
        BlurClass.UNUSABLE:   60,
    }
    score -= blur_penalties.get(blur_class, 35)

    # Brightness
    if brightness_st == "dark":
        score -= 20
    elif brightness_st == "overexposed":
        score -= 15

    # Contrast
    if contrast_st == "low_contrast":
        score -= 10

    # Noise
    if noise_st == "high_noise":
        score -= 15

    # Edge density
    if edge_st == "low_edge_density":
        score -= 10

    # Entropy
    if entropy_st == "low_entropy":
        score -= 10

    # Resolution
    if res_st == "very_low_resolution":
        score -= 20
    elif res_st == "low_resolution":
        score -= 10

    # Glare
    if glare:
        score -= 8

    return max(0, min(100, score))


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_quality(image_input) -> Dict:
    """
    Full quality analysis pipeline.

    Returns:
        {
            "quality_score":  int (0-100),
            "blur_score":     float,
            "blur_class":     str,
            "brightness":     float,
            "contrast":       float,
            "noise":          float,
            "edge_density":   float,
            "entropy":        float,
            "width":          int,
            "height":         int,
            "glare":          bool,
            "quality_flags":  [str],
            "quality_grade":  "EXCELLENT"|"GOOD"|"ACCEPTABLE"|"POOR"|"UNUSABLE",
        }
    """
    gray = _load_gray(image_input)
    if gray is None:
        return {
            "quality_score": 0, "blur_score": 0, "blur_class": BlurClass.UNUSABLE,
            "brightness": 0, "contrast": 0, "noise": 0, "edge_density": 0,
            "entropy": 0, "width": 0, "height": 0, "glare": False,
            "quality_flags": ["image_load_failed"],
            "quality_grade": "UNUSABLE",
        }

    blur_var,   blur_class   = _measure_blur(gray)
    brightness, bright_st    = _measure_brightness(gray)
    contrast,   contrast_st  = _measure_contrast(gray)
    noise,      noise_st     = _measure_noise(gray)
    edge_den,   edge_st      = _measure_edge_density(gray)
    entropy,    entropy_st   = _measure_entropy(gray)
    width, height, res_st    = _measure_resolution(gray)
    glare, glare_st          = _measure_glare(gray)

    quality_score = _compute_quality_score(
        blur_var, blur_class, brightness, bright_st, contrast, contrast_st,
        noise, noise_st, edge_den, edge_st, entropy, entropy_st,
        width, height, res_st, glare,
    )

    # Build flag list
    flags: List[str] = []
    for flag in [blur_class, bright_st, contrast_st, noise_st, edge_st, entropy_st, res_st, glare_st]:
        if flag != "ok" and flag not in (BlurClass.SHARP, BlurClass.ACCEPTABLE):
            flags.append(flag)

    # Grade
    if quality_score >= 80:
        grade = "EXCELLENT"
    elif quality_score >= 65:
        grade = "GOOD"
    elif quality_score >= 45:
        grade = "ACCEPTABLE"
    elif quality_score >= 25:
        grade = "POOR"
    else:
        grade = "UNUSABLE"

    logger.info(
        "[quality_analyzer] score=%d grade=%s blur=%s flags=%s",
        quality_score, grade, blur_class, flags
    )

    return {
        "quality_score":  quality_score,
        "blur_score":     round(blur_var, 2),
        "blur_class":     blur_class,
        "brightness":     round(brightness, 2),
        "contrast":       round(contrast, 2),
        "noise":          noise,
        "edge_density":   edge_den,
        "entropy":        entropy,
        "width":          width,
        "height":         height,
        "glare":          glare,
        "quality_flags":  flags,
        "quality_grade":  grade,
    }
