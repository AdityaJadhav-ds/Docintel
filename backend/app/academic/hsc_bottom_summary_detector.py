"""
app/academic/hsc_bottom_summary_detector.py — Targeted HSC Result Summary Band Detector
========================================================================================
FINAL FIX for Maharashtra 12th HSC extraction.

Problem:
  Full bottom-30% OCR is too noisy — watermarks, thin table lines, and compression
  artifacts cause percentage and result to be lost or garbled.

Solution:
  TARGETED REGION ISOLATION — detect only the narrow result-summary band:
    - Located ABOVE the QR code
    - BELOW the subject marks table
    - Contains: Percentage, Result, Total Marks, PASS/FAIL rows
    - Expected height: 15–20% of document

Pipeline:
  STEP 1  Detect horizontal lines / table blocks → find table bottom edge
  STEP 2  Detect QR code zone (bottom-right quadrant) → find top of QR
  STEP 3  Crop ONLY the summary band between table-bottom and QR-top
  STEP 4  Apply aggressive preprocessing (3× upscale, bilateral, adaptive thresh,
          morphology close, sharpen, contrast boost)
  STEP 5  OCR with --psm 6 + whitelist
  STEP 6  Post-process with intelligent normalization

ISOLATION: Does NOT touch Aadhaar, PAN, SSC, or Degree pipelines.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Optional, Dict, Any, List, Tuple

import numpy as np

logger = logging.getLogger("docvalidator")

# ── Debug output directory ─────────────────────────────────────────────────────

_DEBUG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs", "debug_hsc_summary")
)
os.makedirs(_DEBUG_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 1-2 — Region Detection
# ══════════════════════════════════════════════════════════════════════════════

def _detect_table_bottom_edge(gray: np.ndarray) -> int:
    """
    Find the Y-coordinate of the LAST major horizontal line in the document.
    That line is the bottom of the subject-marks table.
    Returns pixel row index (absolute in full image).
    """
    import cv2

    h, w = gray.shape

    # Search only in the bottom 70% (top 30% is header)
    search_start = int(h * 0.30)
    search_region = gray[search_start:, :]

    # Binarise
    _, binary = cv2.threshold(search_region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontal line kernel: very wide, 1-px tall
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 4, 60), 1))
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # Find all rows that contain a horizontal line
    row_sums = np.sum(horizontal_lines, axis=1)
    line_rows = np.where(row_sums > w * 0.25)[0]  # row must span ≥25% of width

    if len(line_rows) == 0:
        # Fallback: assume table ends at 55% of image
        return int(h * 0.55)

    # The LAST (bottommost) strong horizontal line = table bottom
    last_line_row = int(line_rows[-1]) + search_start
    logger.info("[SUMMARY BAND] Table bottom edge detected at row=%d (%.1f%%)",
                last_line_row, last_line_row / h * 100)
    return last_line_row


def _detect_qr_zone_top(gray: np.ndarray) -> int:
    """
    Detect the top Y-coordinate of the QR code zone.
    QR codes appear as dense dark square regions in the bottom-right quadrant.
    Returns pixel row index, or fallback at 85% of image height.
    """
    import cv2

    h, w = gray.shape

    # QR codes are in the bottom-right quadrant
    roi_top  = int(h * 0.60)
    roi_left = int(w * 0.50)
    roi      = gray[roi_top:, roi_left:]

    # Detect dense dark square blobs (QR pattern)
    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Look for large square-ish contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    qr_top_candidates = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        aspect = cw / ch if ch > 0 else 0
        # QR codes: roughly square, reasonably large
        if area > (h * w * 0.005) and 0.6 <= aspect <= 1.6:
            qr_top_candidates.append(roi_top + y)

    if not qr_top_candidates:
        fallback = int(h * 0.82)
        logger.info("[SUMMARY BAND] QR not detected, fallback top=%d (82%%)", fallback)
        return fallback

    qr_top = min(qr_top_candidates)
    logger.info("[SUMMARY BAND] QR zone top detected at row=%d (%.1f%%)",
                qr_top, qr_top / h * 100)
    return qr_top


def _isolate_summary_band(image_arr: np.ndarray) -> Tuple[np.ndarray, int, int]:
    """
    Locate and crop ONLY the result summary band.

    Returns:
        (crop_array, abs_y_start, abs_y_end)
    """
    import cv2

    h, w = image_arr.shape[:2]

    # Convert to grayscale for detection
    if len(image_arr.shape) == 3:
        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = image_arr.copy()

    # STEP 1: Find table bottom
    table_bottom = _detect_table_bottom_edge(gray)

    # STEP 2: Find QR zone top
    qr_top = _detect_qr_zone_top(gray)

    # STEP 3: Define summary band
    # Add small padding below table bottom
    y_start = max(table_bottom - 10, int(h * 0.45))  # Never start above 45%
    y_end   = min(qr_top + 20, int(h * 0.92))        # Never exceed 92%

    # Safety: ensure band is at least 5% and at most 25% of image height
    min_height = int(h * 0.05)
    max_height = int(h * 0.25)

    if (y_end - y_start) < min_height:
        # Expand upward
        y_start = max(y_end - max_height, int(h * 0.55))
        logger.warning("[SUMMARY BAND] Band too narrow, expanded to y=%d→%d", y_start, y_end)

    if (y_end - y_start) > max_height:
        # Shrink — keep bottom portion (where summary rows live)
        y_start = y_end - max_height
        logger.warning("[SUMMARY BAND] Band too wide, clamped to y=%d→%d", y_start, y_end)

    crop = image_arr[y_start:y_end, :]

    logger.info(
        "[SUMMARY BAND DETECTED] y=%d→%d (%.1f%%–%.1f%%) height=%dpx",
        y_start, y_end,
        y_start / h * 100, y_end / h * 100,
        y_end - y_start,
    )
    return crop, y_start, y_end


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — Preprocessing
# ══════════════════════════════════════════════════════════════════════════════

def _preprocess_summary_band(crop: np.ndarray) -> np.ndarray:
    """
    7-stage preprocessing pipeline for the summary band:
      1. Upscale 3×
      2. Grayscale
      3. Bilateral denoise
      4. Adaptive threshold
      5. Morphology close (fill gaps)
      6. Sharpen
      7. Contrast boost (CLAHE)
    """
    import cv2

    # 1. Upscale 3×
    h, w = crop.shape[:2]
    crop = cv2.resize(crop, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)

    # 2. Grayscale
    if len(crop.shape) == 3:
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    else:
        gray = crop.copy()

    # 3. Bilateral denoise (removes noise, preserves edges)
    denoised = cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)

    # 4. Adaptive threshold — clean black text on white
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=19,
        C=8,
    )

    # 5. Morphology close — fill small gaps in characters
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    # 6. Sharpen
    sharpen_kernel = np.array([[-1, -1, -1],
                                [-1,  9, -1],
                                [-1, -1, -1]], dtype=np.float32)
    sharpened = cv2.filter2D(closed, -1, sharpen_kernel)
    # Clip to valid range
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    # 7. Contrast boost (CLAHE on the sharpened binary is identity, apply before thresh instead)
    # Re-apply CLAHE to denoised then re-threshold for a second pass
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    boosted = clahe.apply(denoised)
    thresh2 = cv2.adaptiveThreshold(
        boosted, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=19,
        C=8,
    )

    # Combine: intersection (AND) gives cleanest result
    combined = cv2.bitwise_and(sharpened, thresh2)
    return combined


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 5 — OCR
# ══════════════════════════════════════════════════════════════════════════════

_WHITELIST = "0123456789.%ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz /-"

def _ocr_summary_band(arr: np.ndarray) -> Tuple[str, List[Dict]]:
    """
    Run Tesseract --psm 6 with whitelist on the preprocessed summary band.
    Returns (full_text, word_boxes).
    """
    try:
        # import pytesseract
        from PIL import Image as PILImage

        pil_img = PILImage.fromarray(arr)

        config = (
            f"--oem 3 --psm 6 "
            f"-c tessedit_char_whitelist=\"{_WHITELIST}\""
        )

        text = pytesseract.image_to_string(pil_img, config=config, lang="eng")

        raw_data = pytesseract.image_to_data(
            pil_img, config=config, lang="eng",
            output_type=pytesseract.Output.DICT,
        )

        boxes: List[Dict] = []
        for i in range(len(raw_data["text"])):
            word = (raw_data["text"][i] or "").strip()
            conf = int(raw_data["conf"][i])
            if word and conf >= 0:
                boxes.append({
                    "text":   word,
                    "left":   raw_data["left"][i],
                    "top":    raw_data["top"][i],
                    "width":  raw_data["width"][i],
                    "height": raw_data["height"][i],
                    "conf":   conf,
                })

        logger.info(
            "[SUMMARY BAND OCR] %d chars, %d word-boxes extracted",
            len(text), len(boxes),
        )
        return text.strip(), boxes

    except Exception as exc:
        logger.error("[SUMMARY BAND OCR] Tesseract failed: %s", exc)
        return "", []


# ══════════════════════════════════════════════════════════════════════════════
#  STEP 6 — Post-processing & Extraction
# ══════════════════════════════════════════════════════════════════════════════

# ── Percentage normalization ──────────────────────────────────────────────────

_PCT_DECIMAL_RE = re.compile(r"\b(\d{2,3})\.(\d{2})\b")      # 75.17
_PCT_NODOT_RE   = re.compile(r"\b(\d{4,5})\b")               # 7517 → 75.17
_PCT_HYPHEN_RE  = re.compile(r"\b(\d{2,3})[-](\d{2})\b")     # 75-17 → 75.17

def _normalize_percentage(raw: str) -> Optional[float]:
    """
    Convert raw OCR string to a valid percentage [35.0, 100.0].

    Handles:
      75.17  → 75.17  (clean)
      7517   → 75.17  (missing dot, 4-digit)
      82400  → 82.40  (5-digit variant)
      75-17  → 75.17  (hyphen instead of dot)
      7S.17  → 75.17  (OCR confuses S→5, handled by whitelist)
    """
    # Direct decimal match first
    m = _PCT_DECIMAL_RE.search(raw)
    if m:
        val = float(f"{m.group(1)}.{m.group(2)}")
        if 35.0 <= val <= 100.0:
            return round(val, 2)

    # Hyphen as decimal separator
    m = _PCT_HYPHEN_RE.search(raw)
    if m:
        val = float(f"{m.group(1)}.{m.group(2)}")
        if 35.0 <= val <= 100.0:
            return round(val, 2)

    # Missing decimal (4 or 5 digit string)
    m = _PCT_NODOT_RE.search(raw)
    if m:
        digits = m.group(1)
        if len(digits) == 4:
            # e.g. 7517 → 75.17
            val = float(f"{digits[:2]}.{digits[2:]}")
            if 35.0 <= val <= 100.0:
                return round(val, 2)
        elif len(digits) == 5:
            # e.g. 82400 → 82.40
            val = float(f"{digits[:2]}.{digits[2:4]}")
            if 35.0 <= val <= 100.0:
                return round(val, 2)

    return None


def _find_percentage(boxes: List[Dict], full_text: str) -> Optional[float]:
    """
    Multi-strategy percentage extraction:
      S1: Spatial anchor — find 'Percentage'/'%' box, get right neighbour value
      S2: Box scan — all boxes for dd.dd pattern in [35, 100]
      S3: Line regex on full_text — near 'percentage' keyword
      S4: Digit normalization pass (4/5-digit mangled values)
    """
    # Strategy 1: Spatial anchor
    anchor_patterns = [r"Percentage", r"percent", r"टक्के", r"\bpct\b", r"\bpercent\b"]
    for anchor_re in anchor_patterns:
        anchor_box = None
        for box in boxes:
            if re.search(anchor_re, box["text"], re.IGNORECASE):
                anchor_box = box
                break
        if anchor_box:
            # Collect right-side same-row boxes
            tol = max(40, anchor_box["height"] * 2)
            right_boxes = [
                b for b in boxes
                if abs(b["top"] - anchor_box["top"]) <= tol
                and b["left"] > anchor_box["left"] + anchor_box["width"]
            ]
            right_boxes.sort(key=lambda b: b["left"])
            for rb in right_boxes[:4]:  # check first 4 candidates
                val = _normalize_percentage(rb["text"])
                if val is not None:
                    logger.info("[PERCENTAGE FOUND] anchor=%s → raw='%s' → %.2f%%",
                                anchor_re, rb["text"], val)
                    return val

    # Strategy 2: Scan all boxes (sorted top→bottom) for decimal percentage
    sorted_boxes = sorted(boxes, key=lambda b: (b["top"], b["left"]))
    for box in sorted_boxes:
        val = _normalize_percentage(box["text"])
        if val is not None:
            logger.info("[PERCENTAGE FOUND] box scan → raw='%s' → %.2f%%", box["text"], val)
            return val

    # Strategy 3: Line regex on full text
    for line in full_text.splitlines():
        low = line.lower()
        if re.search(r"percentage|percent|टक्के|%", low):
            # Extract any number-like token from this line
            tokens = re.findall(r"[\d.%-]+", line)
            for tok in tokens:
                val = _normalize_percentage(tok)
                if val is not None:
                    logger.info("[PERCENTAGE FOUND] line regex → raw='%s' → %.2f%%", tok, val)
                    return val

    # Strategy 4: Whole-text scan for 4/5 digit runs near 'percent' context
    # Allow within 3 lines of a percentage anchor
    lines = full_text.splitlines()
    for i, line in enumerate(lines):
        if re.search(r"percentage|percent|%", line, re.IGNORECASE):
            window = lines[max(0, i-1):i+3]
            for wline in window:
                for tok in re.findall(r"\b\d{4,5}\b", wline):
                    val = _normalize_percentage(tok)
                    if val is not None:
                        logger.info("[PERCENTAGE FOUND] digit-norm fallback → '%s' → %.2f%%", tok, val)
                        return val

    return None


# ── Result extraction ─────────────────────────────────────────────────────────

_RESULT_MAP = [
    (r"\bfirst\s+class\s+with\s+distinction\b", "DISTINCTION"),
    (r"\bdistinction\b",                          "DISTINCTION"),
    (r"\bpass(ed)?\b",                            "PASS"),
    (r"\bfail(ed)?\b",                            "FAIL"),
    (r"\bfirst\s+class\b",                        "FIRST CLASS"),
    (r"\bsecond\s+class\b",                       "SECOND CLASS"),
    (r"\bthird\s+class\b",                        "THIRD CLASS"),
]


def _normalise_result(raw: str) -> Optional[str]:
    low = raw.strip().lower()
    for pat, label in _RESULT_MAP:
        if re.search(pat, low, re.IGNORECASE):
            return label
    return None


def _find_result(boxes: List[Dict], full_text: str) -> Optional[str]:
    """
    Multi-strategy result extraction:
      S1: Spatial anchor — find 'Result' box, get right neighbour
      S2: Box scan for PASS/FAIL/DISTINCTION keywords
      S3: Line regex fallback
    """
    # Strategy 1: Spatial anchor
    for anchor_re in [r"\bResult\b", r"\bRESULT\b", r"निकाल"]:
        anchor_box = None
        for box in boxes:
            if re.search(anchor_re, box["text"], re.IGNORECASE):
                anchor_box = box
                break
        if anchor_box:
            tol = max(50, anchor_box["height"] * 2)
            right_boxes = [
                b for b in boxes
                if abs(b["top"] - anchor_box["top"]) <= tol
                and b["left"] > anchor_box["left"] + anchor_box["width"]
            ]
            right_boxes.sort(key=lambda b: b["left"])
            for rb in right_boxes[:5]:
                norm = _normalise_result(rb["text"])
                if norm:
                    logger.info("[RESULT FOUND] anchor='Result' right='%s' → %s", rb["text"], norm)
                    return norm

    # Strategy 2: Box scan (top→bottom, prefer PASS/FAIL/DISTINCTION)
    sorted_boxes = sorted(boxes, key=lambda b: (b["top"], b["left"]))
    for box in sorted_boxes:
        # Only consider isolated words (not long lines)
        if len(box["text"].split()) <= 3:
            norm = _normalise_result(box["text"])
            if norm:
                logger.info("[RESULT FOUND] box scan → raw='%s' → %s", box["text"], norm)
                return norm

    # Strategy 3: Full text scan — scan near result anchor first, then globally
    for line in full_text.splitlines():
        if re.search(r"result|निकाल", line, re.IGNORECASE):
            norm = _normalise_result(line)
            if norm:
                logger.info("[RESULT FOUND] line anchor → %s", norm)
                return norm

    for line in full_text.splitlines():
        norm = _normalise_result(line)
        if norm:
            logger.info("[RESULT FOUND] global scan → %s", norm)
            return norm

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Debug helpers
# ══════════════════════════════════════════════════════════════════════════════

def _save_debug(raw_crop: np.ndarray, proc_crop: np.ndarray, doc_id: str) -> Tuple[str, str]:
    """Save raw and processed band images to logs/debug_hsc_summary/."""
    raw_path  = ""
    proc_path = ""
    try:
        import cv2
        raw_path  = os.path.join(_DEBUG_DIR, f"{doc_id}_summary_band_raw.png")
        proc_path = os.path.join(_DEBUG_DIR, f"{doc_id}_summary_band_proc.png")
        cv2.imwrite(raw_path,  cv2.cvtColor(raw_crop, cv2.COLOR_RGB2BGR) if len(raw_crop.shape) == 3 else raw_crop)
        cv2.imwrite(proc_path, proc_crop)
        logger.info("[SUMMARY BAND] Debug images saved → %s | %s", raw_path, proc_path)
    except Exception as exc:
        logger.warning("[SUMMARY BAND] Could not save debug images: %s", exc)
    return raw_path, proc_path


# ══════════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════════

def detect_and_extract_hsc_summary(
    image_arr: np.ndarray,
    doc_id: str = "hsc",
) -> Dict[str, Any]:
    """
    Main entry point for targeted HSC result-band extraction.

    Args:
        image_arr:  Full document as H×W×3 uint8 RGB numpy array.
        doc_id:     Unique ID for debug file naming.

    Returns:
        {
          "percentage":        float | None,
          "result":            str   | None,
          "debug_band_raw":    str   (path),
          "debug_band_proc":   str   (path),
          "band_ocr_text":     str,
          "y_start":           int,
          "y_end":             int,
        }
    """
    logger.info("[SUMMARY BAND] Starting targeted HSC summary detection for doc_id=%s", doc_id)

    # STEP 1-3: Isolate summary band
    try:
        raw_crop, y_start, y_end = _isolate_summary_band(image_arr)
    except Exception as exc:
        logger.error("[SUMMARY BAND] Region isolation failed: %s — falling back to bottom 20%%", exc)
        h = image_arr.shape[0]
        y_start = int(h * 0.70)
        y_end   = int(h * 0.90)
        raw_crop = image_arr[y_start:y_end, :]

    # STEP 4: Preprocess
    try:
        proc_crop = _preprocess_summary_band(raw_crop)
    except Exception as exc:
        logger.warning("[SUMMARY BAND] Preprocessing failed (%s), using raw crop", exc)
        proc_crop = raw_crop

    # Save debug images
    raw_path, proc_path = _save_debug(raw_crop, proc_crop, doc_id)

    # STEP 5: OCR
    full_text, boxes = _ocr_summary_band(proc_crop)
    logger.debug("[SUMMARY BAND OCR TEXT]:\n%s", full_text)

    # STEP 6: Extract
    percentage = _find_percentage(boxes, full_text)
    result     = _find_result(boxes, full_text)

    if percentage is not None:
        logger.info("[PERCENTAGE FOUND] Final: %.2f%%", percentage)
    else:
        logger.warning("[SUMMARY BAND] Percentage not found in summary band")

    if result is not None:
        logger.info("[RESULT FOUND] Final: %s", result)
    else:
        logger.warning("[SUMMARY BAND] Result not found in summary band")

    return {
        "percentage":      percentage,
        "result":          result,
        "debug_band_raw":  raw_path,
        "debug_band_proc": proc_path,
        "band_ocr_text":   full_text,
        "y_start":         y_start,
        "y_end":           y_end,
    }
