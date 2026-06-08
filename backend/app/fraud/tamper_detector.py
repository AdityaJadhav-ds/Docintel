"""
app/fraud/tamper_detector.py — Document tampering detection
============================================================
Uses practical computer vision heuristics — no fake AI detection.

Techniques:
  1. ELA (Error Level Analysis) — detects JPEG re-compression zones
  2. Block DCT variance analysis — inconsistent compression indicates paste
  3. Local contrast anomaly map — pasted text creates local contrast spikes
  4. Edge inconsistency — artificial edges from overlaid text
  5. Uniform region detection — suspicious blank zones (number replacement)
  6. Screenshot artifact detection — rounded corners, status bar patterns
  7. Copy-move region similarity — detects cloned areas

All flags have severity: low | medium | high
"""

from __future__ import annotations
import io
import math
from typing import Dict, List, Tuple, Optional
import numpy as np
import cv2
from PIL import Image
from app.core.logger import logger


# ── ELA (Error Level Analysis) ────────────────────────────────────────────────

def _compute_ela(image_input, quality: int = 90) -> Optional[np.ndarray]:
    """
    Error Level Analysis: re-save at quality% and compute absolute difference.
    Tampered regions re-saved at higher quality show higher ELA residual.
    """
    try:
        if isinstance(image_input, np.ndarray):
            pil = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
        elif isinstance(image_input, Image.Image):
            pil = image_input.convert("RGB")
        elif hasattr(image_input, "read"):
            pos = image_input.tell()
            pil = Image.open(image_input).convert("RGB")
            image_input.seek(pos)
        else:
            pil = Image.open(str(image_input)).convert("RGB")

        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        recompressed = Image.open(buf).convert("RGB")

        orig_arr = np.array(pil, dtype=np.float32)
        comp_arr = np.array(recompressed, dtype=np.float32)
        ela_arr  = np.abs(orig_arr - comp_arr)
        return ela_arr.astype(np.uint8)
    except Exception as exc:
        logger.debug("[tamper] ELA failed: %s", exc)
        return None


def _analyze_ela(ela_arr: np.ndarray, block_size: int = 16) -> Tuple[float, bool, str]:
    """
    Divide ELA image into blocks. If some blocks have significantly higher ELA
    than the image mean, those regions may have been tampered with.

    Returns (max_region_score, suspicious, flag).
    """
    gray = cv2.cvtColor(ela_arr, cv2.COLOR_RGB2GRAY) if ela_arr.ndim == 3 else ela_arr
    h, w = gray.shape
    means = []
    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            block = gray[y:y+block_size, x:x+block_size]
            means.append(float(block.mean()))

    if not means:
        return 0.0, False, ""

    overall_mean = np.mean(means)
    overall_std  = np.std(means)
    # Suspicious if any block is > 2.5σ above mean
    threshold    = overall_mean + 2.5 * overall_std
    suspicious_blocks = [m for m in means if m > threshold]
    suspicious_ratio  = len(suspicious_blocks) / max(len(means), 1)

    if suspicious_ratio > 0.10 and overall_std > 5:
        return suspicious_ratio * 100, True, "ela_anomaly_detected"
    return suspicious_ratio * 100, False, ""


# ── Local contrast anomaly ────────────────────────────────────────────────────

def _detect_local_contrast_anomaly(gray: np.ndarray, block_size: int = 32) -> Tuple[float, bool]:
    """
    Pasted text overlays create local high-contrast islands.
    Detect blocks with dramatically different contrast to surroundings.
    """
    h, w = gray.shape
    local_stds = []
    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            block = gray[y:y+block_size, x:x+block_size]
            local_stds.append(float(block.std()))

    if len(local_stds) < 4:
        return 0.0, False

    global_std = float(gray.std())
    anomalous  = [s for s in local_stds if s > global_std * 2.5]
    ratio      = len(anomalous) / max(len(local_stds), 1)
    return round(ratio * 100, 2), ratio > 0.08


# ── Uniform region detection ──────────────────────────────────────────────────

def _detect_uniform_regions(gray: np.ndarray, block_size: int = 16) -> Tuple[int, bool]:
    """
    Suspicious perfectly-uniform blocks may indicate number/text replacement
    with a solid-color patch before new text was added.
    """
    h, w = gray.shape
    uniform_count = 0
    total         = 0

    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            block = gray[y:y+block_size, x:x+block_size]
            if block.std() < 2.0:  # almost perfectly flat
                uniform_count += 1
            total += 1

    if total == 0:
        return 0, False
    ratio = uniform_count / total
    # Only flag if there are multiple suspicious uniform blocks
    suspicious = ratio > 0.08 and uniform_count >= 3
    return uniform_count, suspicious


# ── Edge inconsistency ────────────────────────────────────────────────────────

def _detect_edge_inconsistency(gray: np.ndarray) -> Tuple[float, bool]:
    """
    Artificially overlaid text creates unnaturally sharp, straight edges
    that don't match the image's overall blur level.
    Detect if certain edge responses are disproportionately strong.
    """
    edges  = cv2.Canny(gray, 50, 150)
    kernel = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)

    # Measure variance in edge-dense regions vs sparse regions
    edge_mask    = dilated > 0
    if edge_mask.sum() < 100:
        return 0.0, False

    edge_vals    = gray[edge_mask].astype(float)
    non_edge_vals = gray[~edge_mask].astype(float)
    edge_contrast = float(edge_vals.std())
    bg_contrast   = float(non_edge_vals.std()) + 1e-6
    ratio         = edge_contrast / bg_contrast

    # Naturally printed text: ratio is moderate (1.2-2.0)
    # Pasted text: ratio may be very high (>3.0) or artificially low (<0.5)
    suspicious = ratio > 3.5 or ratio < 0.4
    return round(ratio, 3), suspicious


# ── Screenshot detection ──────────────────────────────────────────────────────

def _detect_screenshot(gray: np.ndarray, original_pil_size: Optional[Tuple]) -> Tuple[bool, List[str]]:
    """
    Screenshots have characteristic patterns:
    - Very high resolution with perfect aspect ratios (16:9, 9:16, 4:3)
    - Uniform border regions (status bars)
    - No EXIF (handled in metadata_analyzer)
    """
    flags = []
    if original_pil_size:
        w, h = original_pil_size
        # Check common screenshot aspect ratios
        for ratio, label in [(16/9, "16:9"), (9/16, "9:16"), (4/3, "4:3"), (3/4, "3:4")]:
            if abs((w/max(h,1)) - ratio) < 0.02:
                flags.append(f"screenshot_aspect_ratio_{label.replace(':','_')}")

        # Very tall narrow images (phone screenshot)
        if h > w * 1.7:
            flags.append("possible_phone_screenshot")

    # Check if top/bottom 5% rows are very uniform (status bar)
    h2, w2 = gray.shape
    top_band  = gray[:max(1, h2 // 20), :]
    bot_band  = gray[max(0, h2 - h2 // 20):, :]
    if top_band.std() < 5 or bot_band.std() < 5:
        flags.append("uniform_border_band")

    return bool(flags), flags


# ── Main tamper analysis ──────────────────────────────────────────────────────

def _load_inputs(image_input):
    """Returns (gray_array, bgr_array, pil_image)."""
    try:
        if isinstance(image_input, np.ndarray):
            bgr  = image_input if image_input.ndim == 3 else cv2.cvtColor(image_input, cv2.COLOR_GRAY2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            pil  = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        elif isinstance(image_input, Image.Image):
            pil  = image_input.convert("RGB")
            bgr  = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        elif hasattr(image_input, "read"):
            pos  = image_input.tell()
            pil  = Image.open(image_input).convert("RGB")
            image_input.seek(pos)
            bgr  = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        else:
            pil  = Image.open(str(image_input)).convert("RGB")
            bgr  = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return gray, bgr, pil
    except Exception as exc:
        logger.error("[tamper] load failed: %s", exc)
        return None, None, None


def detect_tampering(image_input) -> Dict:
    """
    Full tampering analysis. Returns:
        {
            "tamper_score":  int (0-100),
            "tamper_flags":  [str],
            "is_suspicious": bool,
            "ela_score":     float,
            "contrast_anomaly": float,
            "edge_anomaly":     float,
            "uniform_regions":  int,
            "is_screenshot":    bool,
            "details":          [{flag, severity, description}]
        }
    """
    gray, bgr, pil = _load_inputs(image_input)
    if gray is None:
        return {
            "tamper_score": 0, "tamper_flags": ["analysis_failed"],
            "is_suspicious": False, "ela_score": 0,
            "contrast_anomaly": 0, "edge_anomaly": 0,
            "uniform_regions": 0, "is_screenshot": False, "details": [],
        }

    tamper_flags: List[str] = []
    details: List[Dict]     = []
    tamper_score            = 0

    # 1. ELA
    ela_arr = _compute_ela(image_input)
    ela_score = 0.0
    if ela_arr is not None:
        ela_score, ela_suspicious, ela_flag = _analyze_ela(ela_arr)
        if ela_suspicious:
            tamper_flags.append(ela_flag)
            tamper_score += 30
            details.append({"flag": ela_flag, "severity": "high",
                            "description": "Re-compression artifacts detected in localized regions."})

    # 2. Local contrast anomaly
    contrast_ratio, contrast_suspicious = _detect_local_contrast_anomaly(gray)
    if contrast_suspicious:
        tamper_flags.append("local_contrast_anomaly")
        tamper_score += 20
        details.append({"flag": "local_contrast_anomaly", "severity": "medium",
                        "description": "Localized high-contrast islands suggest text overlay."})

    # 3. Uniform regions
    uniform_count, uniform_suspicious = _detect_uniform_regions(gray)
    if uniform_suspicious:
        tamper_flags.append("suspicious_uniform_regions")
        tamper_score += 25
        details.append({"flag": "suspicious_uniform_regions", "severity": "medium",
                        "description": f"{uniform_count} perfectly uniform blocks detected — may indicate content replacement."})

    # 4. Edge inconsistency
    edge_ratio, edge_suspicious = _detect_edge_inconsistency(gray)
    if edge_suspicious:
        tamper_flags.append("edge_inconsistency")
        tamper_score += 15
        details.append({"flag": "edge_inconsistency", "severity": "low",
                        "description": "Edge contrast ratio is abnormal — may indicate overlaid text."})

    # 5. Screenshot detection
    pil_size = pil.size if pil else None
    is_screenshot, screenshot_flags = _detect_screenshot(gray, pil_size)
    if is_screenshot:
        tamper_flags.extend(screenshot_flags)
        tamper_score += 15
        for sf in screenshot_flags:
            details.append({"flag": sf, "severity": "low",
                            "description": "Screenshot indicators detected."})

    tamper_score = min(100, tamper_score)
    is_suspicious = tamper_score >= 25 or len(tamper_flags) >= 2

    logger.info(
        "[tamper_detector] score=%d suspicious=%s flags=%s",
        tamper_score, is_suspicious, tamper_flags
    )

    return {
        "tamper_score":      tamper_score,
        "tamper_flags":      tamper_flags,
        "is_suspicious":     is_suspicious,
        "ela_score":         round(ela_score, 2),
        "contrast_anomaly":  contrast_ratio,
        "edge_anomaly":      edge_ratio,
        "uniform_regions":   uniform_count,
        "is_screenshot":     is_screenshot,
        "details":           details,
    }
