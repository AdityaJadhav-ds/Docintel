"""
academic_engine/scanner/quality_analyzer.py
============================================
STEP 9 — Pre-OCR Quality Analysis.

Measures:
  • blur_score        — Laplacian variance (higher = sharper)
  • brightness_score  — Mean luminance (0–255 mapped to 0–100)
  • contrast_score    — RMS contrast on grayscale
  • skew_score        — Detected skew in degrees (0 = perfect)
  • shadow_score      — Shadow severity (0 = clean, 100 = heavy shadow)
  • readability_score — Composite text readability estimate

Produces:
  {
    "quality_score":     0–100,
    "blur_score":        float,
    "brightness_score":  float,
    "contrast_score":    float,
    "skew_score":        float,
    "shadow_score":      float,
    "readability_score": float,
    "recommendation":    str
  }
"""

from __future__ import annotations

import math
import cv2
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Dict, Any
from app.core.logger import logger


# ── Weights for composite quality score ───────────────────────────────────────
WEIGHTS = {
    "blur":        0.30,
    "brightness":  0.15,
    "contrast":    0.20,
    "skew":        0.10,
    "shadow":      0.15,
    "readability": 0.10,
}


# ── Sub-scorers ───────────────────────────────────────────────────────────────

def _blur_score(gray: np.ndarray) -> float:
    """
    Laplacian variance — high value = sharp image.
    Returns 0–100.  Threshold: < 50 is likely blurry for a document.
    """
    var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Map 0–3000+ variance to 0–100
    score = float(np.clip(math.log1p(var) / math.log1p(3000) * 100, 0, 100))
    return round(score, 2)


def _brightness_score(gray: np.ndarray) -> float:
    """
    Mean luminance mapped to 0–100.
    Target for a good document scan: 140–220 (mean grey).
    Score peaks at mean=180, drops off toward 0 or 255.
    """
    mean  = float(gray.mean())
    # Gaussian-like peak at 180
    score = float(100 * math.exp(-((mean - 180) ** 2) / (2 * 60 ** 2)))
    return round(score, 2)


def _contrast_score(gray: np.ndarray) -> float:
    """
    RMS contrast: std / mean.
    Returns 0–100.  Good documents have RMS contrast 0.2–0.6.
    """
    mean = float(gray.mean())
    std  = float(gray.std())
    rms  = (std / mean) if mean > 0 else 0.0
    score = float(np.clip(rms / 0.5 * 100, 0, 100))
    return round(score, 2)


def _skew_score(gray: np.ndarray) -> float:
    """
    Estimate residual skew (in degrees) via Hough lines.
    Returns angle. 0.0 = perfectly straight.
    """
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=60,
        minLineLength=gray.shape[1] // 5,
        maxLineGap=15,
    )
    if lines is None:
        return 0.0
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 != x1:
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if abs(a) < 45:
                angles.append(abs(a))
    return round(float(np.median(angles)) if angles else 0.0, 2)


def _shadow_score(gray: np.ndarray) -> float:
    """
    Shadow severity score 0–100.
    Uses morphological background std (see shadow_remover).
    """
    try:
        from app.academic_engine.scanner.shadow_remover import estimate_shadow_severity
        sev   = estimate_shadow_severity(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
        return round(sev * 100, 2)
    except Exception:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (71, 71))
        bg     = cv2.dilate(gray, kernel)
        std    = float(np.std(bg.astype(np.float32)))
        return round(float(np.clip(std / 60.0 * 100, 0, 100)), 2)


def _readability_score(gray: np.ndarray) -> float:
    """
    Proxy for text readability:
      • Binarise with Otsu
      • Count text pixels (dark) / total — a healthy document has 3–20% text
      • Penalise images with zero text or > 40% dark (noise or watermark heavy)
    """
    _, bw       = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    text_ratio  = float(bw.sum() // 255) / (bw.shape[0] * bw.shape[1])
    # Peak at 10% text density
    score = float(100 * math.exp(-((text_ratio - 0.10) ** 2) / (2 * 0.08 ** 2)))
    return round(float(np.clip(score, 0, 100)), 2)


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    blur_score:        float = 0.0
    brightness_score:  float = 0.0
    contrast_score:    float = 0.0
    skew_score:        float = 0.0    # degrees
    shadow_score:      float = 0.0
    readability_score: float = 0.0
    quality_score:     float = 0.0
    recommendation:    str   = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _build_recommendation(report: QualityReport) -> str:
    issues = []
    if report.blur_score < 40:
        issues.append("image is blurry — re-capture with steady hands")
    if report.brightness_score < 40:
        issues.append("lighting is uneven or too dark")
    if report.contrast_score < 30:
        issues.append("low contrast — document may be faded")
    if report.skew_score > 5:
        issues.append(f"document is tilted {report.skew_score:.1f}° — straighten camera")
    if report.shadow_score > 60:
        issues.append("heavy shadows detected")
    if report.readability_score < 30:
        issues.append("text density is abnormal — check document content area")

    if not issues:
        if report.quality_score >= 80:
            return "Excellent quality — ready for OCR."
        return "Good quality — OCR should work reliably."
    return "Issues: " + "; ".join(issues) + "."


def analyze_quality(image: np.ndarray) -> QualityReport:
    """
    Analyse document image quality and return a QualityReport.

    Args:
        image: BGR numpy array (the *restored* image, post-pipeline)

    Returns:
        QualityReport with individual sub-scores and composite quality_score.
    """
    if image is None or image.size == 0:
        logger.warning("[quality_analyzer] Empty image — returning zero report")
        r = QualityReport(recommendation="No image provided.")
        return r

    h, w = image.shape[:2]
    logger.info("[quality_analyzer] Analysing %dx%d image", w, h)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    blur   = _blur_score(gray)
    bright = _brightness_score(gray)
    cont   = _contrast_score(gray)
    skew   = _skew_score(gray)
    shadow = _shadow_score(gray)
    read   = _readability_score(gray)

    # Composite — skew is penalised (lower skew_degrees = better)
    skew_penalty = float(np.clip(skew / 10.0, 0, 1))   # 0–1, 0 = good
    skew_100     = float(np.clip((1 - skew_penalty) * 100, 0, 100))

    composite = (
        WEIGHTS["blur"]        * blur
        + WEIGHTS["brightness"]  * bright
        + WEIGHTS["contrast"]    * cont
        + WEIGHTS["skew"]        * skew_100
        + WEIGHTS["shadow"]      * (100 - shadow)  # lower shadow = better
        + WEIGHTS["readability"] * read
    )
    composite = round(float(np.clip(composite, 0, 100)), 2)

    report = QualityReport(
        blur_score        = blur,
        brightness_score  = bright,
        contrast_score    = cont,
        skew_score        = skew,
        shadow_score      = shadow,
        readability_score = read,
        quality_score     = composite,
    )
    report.recommendation = _build_recommendation(report)

    logger.info(
        "[quality_analyzer] quality=%.1f blur=%.1f bright=%.1f contrast=%.1f "
        "skew=%.1f° shadow=%.1f read=%.1f",
        composite, blur, bright, cont, skew, shadow, read,
    )
    return report
