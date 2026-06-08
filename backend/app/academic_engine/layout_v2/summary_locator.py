"""
academic_engine/layout_v2/summary_locator.py
=============================================
Summary Zone Locator — OCR-Tuned for WhatsApp/Mobile Images.

TUNING CHANGES (Phase 4 + 5 — Critical System Tuning):
  - MIN_WORD_CONF lowered 20→10 to not drop noisy WhatsApp words
  - PERCENTAGE_KEYWORDS expanded with OCR-noise variants
  - Added numeric-scan fallback: find XX.XX pattern even without label
  - Added _repair_numeric_ocr() for recovery: 7517→75.17, 7S.17→75.17
  - search_rows expanded to 3 for below-label value search
  - Upscale threshold lowered from 600→400px to trigger sooner
  - Full crop returned as percentage fallback even with partial anchors
"""

from __future__ import annotations

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.core.logger import logger
from app.academic_engine.layout_v2.spatial_relationships import (
    BBox, group_into_rows, bbox_center, enclosing_bbox, same_row, vertical_distance
)

# ── Constants ─────────────────────────────────────────────────────────────────

ROI_PAD_X = 10
ROI_PAD_Y = 6

# Lowered from 20 to capture more words from WhatsApp-compressed images
MIN_WORD_CONF = 10

PERCENTAGE_KEYWORDS = {
    # English variants
    "percentage", "percent", "total%", "per cent", "per-cent",
    "marks%", "overall%", "aggregate", "total percentage",
    "percentage of marks", "perc", "pct",
    # OCR noise variants
    "percentaoe", "percentaqe", "percertage", "percentag",
    "p3rcent", "percen", "percentaye",
    # Symbol variants — OCR sometimes reads "%" standalone
    "%",
    # Marathi / Hindi
    "एकूण टक्के", "टक्के", "टक्केवारी",
    "प्रतिशत",
}
CGPA_KEYWORDS = {
    "cgpa", "sgpa", "gpa", "grade point", "cumulative",
    "c.g.p.a", "grade pt",
}
RESULT_KEYWORDS = {
    "result", "रिझल्ट", "परिणाम", "decision", "निर्णय",
    "pass", "fail", "distinction", "first class", "second class", "third class",
    "उत्तीर्ण", "अनुत्तीर्ण", "outcome",
}
NOISE_KEYWORDS = {
    "subject", "code", "total", "marks", "obtained", "maximum",
    "theory", "practical", "internal", "external", "written",
    "sub", "max",
}

# 3-digit integers that are NEVER percentages — total/max marks columns
# Updated when a label in same row is one of these
_TOTAL_MARKS_LABELS = re.compile(
    r"\b(total|max|maximum|obtained|marks|टक्के|एकूण)\b", re.IGNORECASE
)


# ── Numeric OCR repair ────────────────────────────────────────────────────────

def _repair_numeric_ocr(text: str) -> str:
    """
    Repair common OCR confusions in numeric strings.
    Examples: 7517 → 75.17  |  7S.17 → 75.17  |  75:17 → 75.17
    """
    # Replace letter-in-number confusions
    t = text.strip()
    t = re.sub(r"[Ss]", "5", t)
    t = re.sub(r"[Oo]", "0", t)
    t = re.sub(r"[Il|]", "1", t)
    t = re.sub(r"[Bb]", "8", t)
    t = re.sub(r"[Zz]", "2", t)
    # Colon/semicolon → dot
    t = re.sub(r"[:;]", ".", t)
    # Space inside number → dot if it looks like decimal split
    # e.g. "75 17" → "75.17" when both parts look like number pieces
    m = re.match(r"^(\d{1,3})\s+(\d{1,2})$", t.strip())
    if m:
        whole, dec = m.group(1), m.group(2)
        # Only insert dot if the result makes sense as a percentage
        candidate = f"{whole}.{dec}"
        try:
            if 0.0 < float(candidate) <= 100.0:
                t = candidate
        except ValueError:
            pass

    # 4-digit run without dot → try inserting dot at pos 2
    # e.g. "7517" → "75.17"
    m = re.fullmatch(r"(\d{2})(\d{2})", t)
    if m:
        candidate = f"{m.group(1)}.{m.group(2)}"
        try:
            if 0.0 < float(candidate) <= 100.0:
                t = candidate
        except ValueError:
            pass

    return t


def _is_total_marks(value: float, text: str) -> bool:
    """
    Returns True if this number looks like a total/max marks column value
    rather than a percentage.
    - 3-digit integers (300, 450, 500, 600) are never percentages
    - Values > 100 are never percentages
    - Exact integers >= 150 are suspicious
    """
    if value > 100.0:
        return True
    # 3-digit integers with no decimal: definitely marks column
    stripped = text.strip().rstrip("%")
    if re.fullmatch(r"\d{3}", stripped):
        return True
    # Exact integer >= 150 (e.g. 600, 451) — marks not percentage
    if value >= 150:
        return True
    return False


def _parse_percentage_from_text(text: str) -> Optional[str]:
    """Extract and validate a percentage value from raw OCR text."""
    repaired = _repair_numeric_ocr(text)
    for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,4})?)\b", repaired):
        try:
            v = float(m.group(1))
            if not (0.5 <= v <= 100.0):
                continue
            if _is_total_marks(v, m.group(1)):
                continue
            return f"{v:.2f}"
        except ValueError:
            pass
    return None


def _is_valid_pct_value(text: str) -> bool:
    """Return True if text represents a valid, plausible academic percentage (>= 10.0)."""
    if not text:
        return False
    try:
        v = float(text.strip().rstrip("%"))
        return v >= 10.0 and not _is_total_marks(v, text)
    except (ValueError, AttributeError):
        return False



# ── ROI preprocessing ─────────────────────────────────────────────────────────

def _preprocess_for_ocr_data(roi: np.ndarray) -> np.ndarray:
    """Prepare summary zone for Tesseract image_to_data (word-level bboxes)."""
    if roi is None or roi.size == 0:
        return roi
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi.copy()
    # CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    # Upscale if too small (lowered threshold from 600→400)
    h, w = gray.shape
    if w < 400:
        scale = 400 / w
        gray  = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    return gray


def _preprocess_percentage_roi(roi: np.ndarray) -> np.ndarray:
    """
    Aggressive 4x upscale + denoise + threshold pipeline
    specifically for the percentage value ROI.
    """
    if roi is None or roi.size == 0:
        return roi
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi.copy()
    # 4x upscale
    h, w = gray.shape
    gray = cv2.resize(gray, (w * 4, h * 4), interpolation=cv2.INTER_LANCZOS4)
    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    gray  = clahe.apply(gray)
    # Sharpen
    kernel = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]], dtype=np.float32)
    gray   = cv2.filter2D(gray, -1, kernel)
    # Adaptive threshold
    gray = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 15, 8
    )
    # Morphological close to fill gaps
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    gray    = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel2)
    return gray


# ── Tesseract word-level data extraction ─────────────────────────────────────

def _get_word_data(gray: np.ndarray) -> List[Dict]:
    """Run Tesseract image_to_data and return word records above MIN_WORD_CONF."""
    try:
        # import pytesseract
        data = pytesseract.image_to_data(
            gray,
            config="--oem 3 --psm 6",
            lang="eng",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        logger.warning("[summary_locator] Tesseract data failed: %s", exc)
        return []

    words = []
    n = len(data.get("text", []))
    for i in range(n):
        text = str(data["text"][i]).strip()
        conf = data["conf"][i]
        if not text:
            continue
        # Accept words with conf >= MIN_WORD_CONF OR if text looks numeric
        if isinstance(conf, (int, float)) and conf < MIN_WORD_CONF:
            if not re.search(r"\d", text):
                continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        if w > 0 and h > 0:
            words.append({"text": text, "conf": float(conf), "bbox": (x, y, w, h)})
    return words


def _ocr_percentage_numeric(roi: np.ndarray) -> Optional[str]:
    """
    Run Tesseract with PSM 7 + numeric whitelist on the percentage ROI.
    Returns parsed percentage string or None.
    """
    try:
        # import pytesseract
        processed = _preprocess_percentage_roi(roi)
        raw = pytesseract.image_to_string(
            processed,
            config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.",
            lang="eng",
        ).strip()
        logger.debug("[summary_locator] Numeric-OCR raw: %r", raw)
        return _parse_percentage_from_text(raw)
    except Exception as exc:
        logger.warning("[summary_locator] Numeric OCR failed: %s", exc)
        return None


def _ocr_percentage_color_channels(roi: np.ndarray) -> Optional[str]:
    """
    Extract percentage by isolating individual color channels.

    Maharashtra HSC marksheets print the percentage value in a colored cell
    (cyan/teal background). Grayscale conversion loses the contrast needed
    for OCR. Scanning R/G/B channels independently recovers the number.

    Returns the best validated percentage string, or None.
    """
    if roi is None or roi.size == 0:
        return None
    if len(roi.shape) < 3 or roi.shape[2] < 3:
        return None  # already grayscale — nothing to split

    try:
        # import pytesseract
        b, g, r = cv2.split(roi)
        candidates: list = []

        for chan, name in [(r, "R"), (g, "G")]:  # R and G channels most effective
            # 4x upscale
            h, w = chan.shape
            up = cv2.resize(chan, (w * 4, h * 4), interpolation=cv2.INTER_LANCZOS4)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
            up = clahe.apply(up)
            _, thr = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            for psm in ("6", "7"):
                try:
                    raw = pytesseract.image_to_string(
                        thr,
                        config=f"--oem 3 --psm {psm}",
                        lang="eng",
                    ).strip()
                    # Find XX.XX pattern
                    for m in re.finditer(r"\b(\d{1,2}\.\d{1,2})\b", raw):
                        try:
                            v = float(m.group(1))
                            if 10.0 <= v <= 100.0:
                                candidates.append((v, name, psm, m.group(1)))
                        except ValueError:
                            pass
                except Exception:
                    pass

        if not candidates:
            return None

        # Pick the most common value (mode) to handle slight channel variations
        from collections import Counter
        # Round to 1 decimal for grouping (78.17 and 78.47 → both near 78.x)
        rounded = [round(v, 0) for v, *_ in candidates]
        most_common_int = Counter(rounded).most_common(1)[0][0]
        # Among matches at that integer, pick the one closest to X5.17 format (decimal values)
        group = [(v, txt) for v, *_, txt in candidates if round(v, 0) == most_common_int]
        # Prefer values with .17 / .33 / .67 (1/6 increments common in Indian marksheets)
        best = sorted(group, key=lambda t: abs(t[0] - round(t[0])))[0]
        result = f"{best[0]:.2f}"

        logger.info("[summary_locator] Color-channel OCR found percentage: %s (from %d candidates: %s)",
                    result, len(candidates), candidates)
        return result

    except Exception as exc:
        logger.warning("[summary_locator] Color-channel OCR failed: %s", exc)
        return None


def _ocr_percentage_with_channels(roi: np.ndarray) -> Optional[str]:
    """Try numeric OCR first, then color-channel fallback."""
    val = _ocr_percentage_numeric(roi)
    if val:
        return val
    return _ocr_percentage_color_channels(roi)


def _compute_pct_from_marks(summary_crop: np.ndarray) -> Optional[str]:
    """
    Compute percentage arithmetically from Obtained/Total marks.

    Maharashtra HSC/SSC marksheets print the percentage in a colored cell that
    is unreliable for direct OCR. However, 'Total Marks' and 'Obtained Marks'
    are printed as plain integers on white background — much easier to read.

    Strategy:
      1. OCR the full summary zone to get all digit strings.
      2. Repair common OCR substitutions ($→6, S→5, O→0, l→1).
      3. Find the pair (total, obtained) where total >= obtained,
         total is a 'round' number (multiples of 50/100), and
         their ratio matches the ballpark percentage from color-channel OCR.
      4. Compute round(obtained/total * 100, 2) and validate.

    Returns exact percentage string or None.
    """
    if summary_crop is None or summary_crop.size == 0:
        return None
    try:
        # import pytesseract

        def _repair_ocr(text: str) -> str:
            """Fix common OCR character substitutions in digit strings."""
            # Only repair characters that are within/adjacent to digit sequences
            repaired = re.sub(r'(?<=\d)[SOsl](?=\d)', '0', text)  # internal
            repaired = re.sub(r'\$(\d{2})', r'6\1', repaired)     # $00 → 600
            repaired = re.sub(r'[SOsl](\d{2})', r'6\1', repaired)  # S00 → 600
            repaired = re.sub(r'(\d{2})[SOsl]', r'\g<1>0', repaired)  # 60S → 600
            return repaired

        # Run OCR on full summary zone
        gray = cv2.cvtColor(summary_crop, cv2.COLOR_BGR2GRAY) \
               if len(summary_crop.shape) == 3 else summary_crop
        h, w = gray.shape
        up = cv2.resize(gray, (w * 4, h * 4), interpolation=cv2.INTER_LANCZOS4)
        _, thr = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        raw_text = pytesseract.image_to_string(
            thr, config="--oem 3 --psm 6", lang="eng"
        )
        repaired = _repair_ocr(raw_text)
        all_nums = re.findall(r'\d+', repaired)
        three_digit = [int(n) for n in all_nums if len(n) == 3 and 100 <= int(n) <= 900]

        if len(three_digit) < 2:
            return None

        # Try all (total, obtained) candidate pairs
        best = None
        for total in three_digit:
            for obtained in three_digit:
                if obtained >= total:
                    continue
                if total < 300:
                    continue  # total marks < 300 is implausible for full board exam
                pct = round(obtained / total * 100, 2)
                if 30.0 <= pct <= 99.9:
                    # Score by: round total (multiples of 50 are common)
                    roundness = (total % 50 == 0) * 10 + (total % 100 == 0) * 10
                    score = roundness + pct  # higher pct = more plausible student
                    if best is None or score > best[2]:
                        best = (total, obtained, score, pct)

        if best:
            total, obtained, _, pct = best
            result = f"{pct:.2f}"
            logger.info(
                "[summary_locator] Marks-arithmetic pct: %s/%s*100 = %s",
                obtained, total, result,
            )
            return result

        return None

    except Exception as exc:
        logger.warning("[summary_locator] Marks-arithmetic failed: %s", exc)
        return None


# ── Anchor classification ─────────────────────────────────────────────────────

def _classify_anchor(text: str) -> str:
    t = text.lower().strip(".:-/%\u0964")
    if t in NOISE_KEYWORDS:
        return "noise"
    # Check percentage keywords (normalized)
    for kw in PERCENTAGE_KEYWORDS:
        if kw in t or t in kw:
            return "percentage_label"
    if any(kw in t for kw in CGPA_KEYWORDS):
        return "cgpa_label"
    if any(kw in t for kw in RESULT_KEYWORDS):
        return "result_label"
    # Numeric: digits with optional dot/percent
    cleaned = _repair_numeric_ocr(text)
    if re.fullmatch(r"\d{1,3}(\.\d{1,2})?%?", cleaned):
        return "numeric"
    if re.fullmatch(r"\d{1,3}(\.\d{1,2})?%?", text):
        return "numeric"
    # Result value
    if re.fullmatch(r"[A-Za-z\s]+", text) and t in RESULT_KEYWORDS:
        return "result_value"
    return "other"


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FieldROI:
    label:      str
    label_bbox: Optional[BBox]
    value_bbox: Optional[BBox]
    roi:        Optional[np.ndarray]
    value_text: str = ""
    confidence: float = 0.0

    def __repr__(self) -> str:
        shape = self.roi.shape if self.roi is not None else None
        return f"FieldROI({self.label!r}, value={self.value_text!r}, conf={self.confidence:.2f}, shape={shape})"


@dataclass
class SummaryLocatorResult:
    found:          bool = False
    full_text:      str  = ""
    percentage_roi: Optional[FieldROI] = None
    cgpa_roi:       Optional[FieldROI] = None
    result_roi:     Optional[FieldROI] = None
    anchors:        List[Dict] = field(default_factory=list)
    debug_words:    List[Dict] = field(default_factory=list)

    def get_all_rois(self) -> Dict[str, Optional[FieldROI]]:
        return {
            "percentage": self.percentage_roi,
            "cgpa":       self.cgpa_roi,
            "result":     self.result_roi,
        }


# ── ROI crop helpers ──────────────────────────────────────────────────────────

def _crop_roi_around_bbox(
    image: np.ndarray,
    bbox:  BBox,
    pad_x: int = ROI_PAD_X,
    pad_y: int = ROI_PAD_Y,
) -> Optional[np.ndarray]:
    x, y, w, h = bbox
    ih, iw = image.shape[:2]
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(iw, x + w + pad_x)
    y2 = min(ih, y + h + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    return image[y1:y2, x1:x2].copy()


def _extended_value_bbox(
    label_bbox: BBox,
    words:      List[Dict],
    image_w:    int,
    search_rows: int = 3,    # increased from 2→3
) -> Optional[BBox]:
    lx, ly, lw, lh = label_bbox
    label_mid_y  = ly + lh / 2
    label_right  = lx + lw

    candidates = []
    for w_rec in words:
        wx, wy, ww, wh = w_rec["bbox"]
        wt      = w_rec["text"]
        w_mid_y = wy + wh / 2
        w_type  = _classify_anchor(wt)

        if w_type not in ("numeric", "result_value", "other"):
            continue

        vertical_gap = w_mid_y - label_mid_y
        if vertical_gap < -lh or vertical_gap > search_rows * lh * 1.8:
            continue

        if wx < lx - 20 and not same_row(label_bbox, w_rec["bbox"], tolerance_px=lh):
            continue

        dist = ((wx - label_right) ** 2 + (w_mid_y - label_mid_y) ** 2) ** 0.5
        candidates.append((dist, w_rec["bbox"], wt))

    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]


# ── Percentage-specific numeric scan ─────────────────────────────────────────

def _scan_for_percentage_value(words: List[Dict], image: np.ndarray) -> Optional[FieldROI]:
    """
    Fallback: scan all words for a value that looks like a valid percentage.
    STRICT: Must have a decimal point (75.17 yes, 451 no, 600 no).
    Rejects any 3-digit integers which are total/max marks.
    Returns FieldROI or None.
    """
    h, w = image.shape[:2]
    lower_threshold = h * 0.3

    # Build a set of row-contexts to detect total/marks labels
    # If a word is on the same row as "Total Marks" / "Obtained", skip its numerics
    noise_rows: set = set()
    for wr in words:
        if _classify_anchor(wr["text"]) == "noise":
            # Mark this row's y-midpoint as a noise row
            bx, by, bw, bh = wr["bbox"]
            noise_rows.add(by // 20)  # 20px bucket

    candidates = []
    for wr in words:
        bx, by, bw, bh = wr["bbox"]
        if by < lower_threshold:
            continue
        # Skip if this word is on a noise row (marks/obtained label row)
        if (by // 20) in noise_rows:
            continue
        raw = wr["text"]
        rep = _repair_numeric_ocr(raw)
        # STRICT: must contain a decimal point after repair
        m = re.fullmatch(r"(\d{1,2}\.\d{1,2})%?", rep.strip())
        if not m:
            continue
        try:
            v = float(m.group(1))
            if 0.5 <= v <= 100.0 and not _is_total_marks(v, m.group(1)):
                candidates.append((by, wr, rep, v))
        except ValueError:
            continue

    if not candidates:
        return None

    # Prefer bottommost candidate (summary totals at bottom)
    candidates.sort(key=lambda t: t[0], reverse=True)
    _, best_wr, best_rep, best_val = candidates[0]
    bbox = best_wr["bbox"]
    roi  = _crop_roi_around_bbox(image, bbox, pad_x=20, pad_y=10)

    logger.info("[summary_locator] Numeric scan found percentage: %s", f"{best_val:.2f}")
    return FieldROI(
        label      = "percentage",
        label_bbox = None,
        value_bbox = bbox,
        roi        = roi,
        value_text = f"{best_val:.2f}",
        confidence = 0.65,
    )


# ── Main locator ──────────────────────────────────────────────────────────────

class SummaryLocator:

    def locate(
        self,
        summary_crop: np.ndarray,
        color_crop:   Optional[np.ndarray] = None,
    ) -> SummaryLocatorResult:
        """
        color_crop: original (pre-restoration) summary zone for color-channel extraction.
        If None, summary_crop is used for everything.
        """
        if summary_crop is None or summary_crop.size == 0:
            logger.warning("[summary_locator] Empty summary crop")
            return SummaryLocatorResult()

        # Store color_crop as instance variable for use in color-channel pass
        self._color_crop = color_crop if color_crop is not None else summary_crop

        h, w = summary_crop.shape[:2]
        logger.info("[summary_locator] Summary crop: %dx%d", w, h)

        # Preprocess for data OCR
        gray    = _preprocess_for_ocr_data(summary_crop)
        scale_x = w / gray.shape[1]
        scale_y = h / gray.shape[0]

        words = _get_word_data(gray)
        logger.info("[summary_locator] Words found: %d", len(words))

        if not words:
            logger.warning("[summary_locator] No words in summary zone — returning full crop")
            return SummaryLocatorResult(
                found=True,
                full_text="",
                percentage_roi=FieldROI(
                    label="percentage", label_bbox=None, value_bbox=None,
                    roi=summary_crop.copy(), confidence=0.2,
                ),
            )

        # Rescale bboxes back to original coordinates
        def rescale(bbox: BBox) -> BBox:
            x, y, bw, bh = bbox
            return (
                int(x * scale_x), int(y * scale_y),
                int(bw * scale_x), int(bh * scale_y),
            )

        scaled_words = [{**wr, "bbox": rescale(wr["bbox"])} for wr in words]

        for wr in scaled_words:
            wr["type"] = _classify_anchor(wr["text"])

        full_text = " ".join(wr["text"] for wr in scaled_words if wr["type"] != "noise")

        result = SummaryLocatorResult(
            found      = True,
            full_text  = full_text,
            debug_words= scaled_words,
        )

        # ── Percentage ROI ────────────────────────────────────────────────
        result.percentage_roi = self._find_field_roi(
            scaled_words, summary_crop, "percentage_label", label_name="percentage",
        )

        # ── CGPA ROI ─────────────────────────────────────────────────────
        result.cgpa_roi = self._find_field_roi(
            scaled_words, summary_crop, "cgpa_label", label_name="cgpa",
        )

        # ── Result ROI ───────────────────────────────────────────────────
        result.result_roi = self._find_field_roi(
            scaled_words, summary_crop, "result_label", label_name="result",
        )

        # ── Fallback: numeric scan for percentage ─────────────────────────
        if result.percentage_roi is None and result.cgpa_roi is None:
            numeric_froi = _scan_for_percentage_value(scaled_words, summary_crop)
            if numeric_froi:
                result.percentage_roi = numeric_froi
            else:
                logger.info("[summary_locator] No anchors & no numeric scan — full crop fallback")
                result.percentage_roi = FieldROI(
                    label="percentage", label_bbox=None, value_bbox=None,
                    roi=summary_crop.copy(), confidence=0.2,
                )

        # ── Color-channel targeted extraction ─────────────────────────────
        # For Maharashtra HSC/SSC marksheets, the percentage value is printed
        # in a colored cell (cyan/teal). Grayscale OCR misses it.
        # Use self._color_crop (original unrestored image) to preserve color fidelity.
        current_pct = (result.percentage_roi.value_text if result.percentage_roi else "")
        if not current_pct or (current_pct and not _is_valid_pct_value(current_pct)):
            arithmetic_val = _compute_pct_from_marks(self._color_crop)
            chan_val = None
            if arithmetic_val:
                chan_val = arithmetic_val
                logger.info("[summary_locator] Using marks-arithmetic for percentage: %s", chan_val)
            else:
                color_src = self._color_crop  # original image — better color contrast
                csh, csw = color_src.shape[:2]
                # Left portion: percentage cell is in x=[0, 35%], y=[0, 55%] of summary zone
                pct_cell = color_src[0:int(csh * 0.55), 0:int(csw * 0.35)]
                chan_val = _ocr_percentage_color_channels(pct_cell)
                if not chan_val:
                    # Wider crop fallback
                    pct_cell_wide = color_src[0:int(csh * 0.55), :]
                    chan_val = _ocr_percentage_color_channels(pct_cell_wide)
                if not chan_val:
                    # Last resort: full color source zone
                    chan_val = _ocr_percentage_color_channels(color_src)
            if chan_val:
                logger.info("[summary_locator] Color-channel targeted crop: %s (from %s)",
                            chan_val, "original" if self._color_crop is not summary_crop else "restored")
                if result.percentage_roi is None:
                    result.percentage_roi = FieldROI(
                        label="percentage", label_bbox=None, value_bbox=None,
                        roi=pct_cell, value_text=chan_val, confidence=0.70,
                    )
                else:
                    result.percentage_roi.value_text = chan_val
                    result.percentage_roi.confidence = max(result.percentage_roi.confidence, 0.70)

        # ── Post-process: run channel OCR on percentage ROI if still empty ─
        if result.percentage_roi and result.percentage_roi.roi is not None:
            if not result.percentage_roi.value_text:
                val = _ocr_percentage_with_channels(result.percentage_roi.roi)
                if val:
                    result.percentage_roi.value_text = val
                    result.percentage_roi.confidence = max(result.percentage_roi.confidence, 0.65)
                    logger.info("[summary_locator] Channel OCR recovered percentage: %s", val)

        self._log_result(result)
        return result

    def _find_field_roi(
        self,
        words:      List[Dict],
        image:      np.ndarray,
        label_type: str,
        label_name: str,
    ) -> Optional[FieldROI]:
        label_words = [w for w in words if w["type"] == label_type]
        if not label_words:
            return None

        best_label = max(label_words, key=lambda w: w["conf"])
        label_bbox = best_label["bbox"]
        value_bbox = _extended_value_bbox(label_bbox, words, image.shape[1])

        boxes = [label_bbox]
        if value_bbox:
            boxes.append(value_bbox)
        enc = enclosing_bbox(boxes) or label_bbox

        # Wider padding for percentage ROI to catch nearby value
        pad_x = 25 if label_name == "percentage" else 15
        pad_y = 12 if label_name == "percentage" else 8
        roi = _crop_roi_around_bbox(image, enc, pad_x=pad_x, pad_y=pad_y)

        value_text = ""
        if value_bbox:
            value_text = " ".join(
                w["text"] for w in words
                if same_row(value_bbox, w["bbox"], tolerance_px=18)
                and _classify_anchor(w["text"]) in ("numeric", "result_value", "other")
            )

        conf = best_label["conf"] / 100.0

        # If we have a percentage label, try aggressive numeric OCR on the ROI
        numeric_val = None
        if label_name == "percentage" and roi is not None:
            numeric_val = _ocr_percentage_with_channels(roi)
            if numeric_val:
                value_text = numeric_val
                conf = max(conf, 0.75)

        return FieldROI(
            label      = label_name,
            label_bbox = label_bbox,
            value_bbox = value_bbox,
            roi        = roi,
            value_text = (numeric_val or value_text).strip(),
            confidence = conf,
        )

    @staticmethod
    def _log_result(result: SummaryLocatorResult) -> None:
        logger.info(
            "[summary_locator] Located — pct=%s(%s) cgpa=%s result=%s text_len=%d",
            result.percentage_roi is not None,
            result.percentage_roi.value_text if result.percentage_roi else "—",
            result.cgpa_roi is not None,
            result.result_roi is not None,
            len(result.full_text),
        )


_locator = SummaryLocator()


def locate_summary(
    summary_crop: np.ndarray,
    color_crop:   Optional[np.ndarray] = None,
) -> SummaryLocatorResult:
    """
    Locate summary fields in the summary zone crop.
    color_crop: optional original (pre-restoration) image crop for color-channel
                percentage extraction. If None, summary_crop is used.
    """
    return _locator.locate(summary_crop, color_crop=color_crop)
