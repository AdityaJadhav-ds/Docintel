"""
app/academic/academic_document_layout_engine.py
================================================
Full root-cause rebuild: region-based academic document extraction.

Architecture:
  ZONE A → Header   (board, doc type)
  ZONE B → Candidate (anchor-based precise name extraction)
  ZONE C → Subject table (skipped for performance)
  ZONE D → Result summary (result, CGPA)
  ZONE P → Percentage ROI (bottom-left corner above QR)
  ZONE E → QR/Hologram (MASKED OUT)

ISOLATION: Never touches Aadhaar/PAN pipelines.
"""

from __future__ import annotations
import os, re, logging
from typing import Optional, Dict, Any, Tuple, List

import numpy as np

logger = logging.getLogger("docvalidator")

_DEBUG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "logs", "academic_debug")
)
os.makedirs(_DEBUG_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# CV helpers
# ─────────────────────────────────────────────────────────────────────────────

def _to_gray(img: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img.copy()

def _save(arr: np.ndarray, doc_id: str, tag: str) -> str:
    try:
        import cv2
        p = os.path.join(_DEBUG_DIR, f"{doc_id}_{tag}.png")
        cv2.imwrite(p, arr)
        return p
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# ZONE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _find_table_bottom(gray: np.ndarray) -> int:
    import cv2
    h, w = gray.shape
    start = int(h * 0.30)
    roi = gray[start:, :]
    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kw = max(w // 5, 40)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    rows = np.where(np.sum(lines, axis=1) > w * 0.20)[0]
    if not len(rows):
        return int(h * 0.58)
    return int(rows[-1]) + start

def _find_qr_top(gray: np.ndarray) -> int:
    import cv2
    h, w = gray.shape
    roi_y = int(h * 0.60)
    roi_x = int(w * 0.45)
    roi = gray[roi_y:, roi_x:]
    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tops = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        asp = cw / ch if ch > 0 else 0
        if area > h * w * 0.004 and 0.55 <= asp <= 1.8:
            tops.append(roi_y + y)
    return min(tops) if tops else int(h * 0.82)

def _segment_zones(img: np.ndarray) -> Dict[str, Tuple[int,int]]:
    h, w = img.shape[:2]
    gray = _to_gray(img)

    table_bottom = _find_table_bottom(gray)
    qr_top       = _find_qr_top(gray)

    table_bottom = max(int(h * 0.40), min(table_bottom, int(h * 0.75)))
    qr_top       = max(int(h * 0.65), min(qr_top,       int(h * 0.92)))

    summary_y0 = max(table_bottom - 15, int(h * 0.45))
    summary_y1 = min(qr_top + 10,       int(h * 0.92))

    if summary_y1 - summary_y0 < int(h * 0.05):
        summary_y0 = max(0, summary_y1 - int(h * 0.20))

    return {
        "header":    (0,            int(h * 0.22)),
        "candidate": (int(h * 0.18), int(h * 0.45)),
        "summary":   (summary_y0,   summary_y1),
        "qr_mask":   (qr_top,       h),
    }

# ─────────────────────────────────────────────────────────────────────────────
# ZONE PREPROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def _prep_header(crop: np.ndarray) -> np.ndarray:
    import cv2
    g = _to_gray(crop)
    g = cv2.resize(g, (g.shape[1]*2, g.shape[0]*2), interpolation=cv2.INTER_LINEAR)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    g = clahe.apply(g)
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8)

def _prep_candidate(crop: np.ndarray) -> np.ndarray:
    import cv2
    g = _to_gray(crop)
    g = cv2.resize(g, (g.shape[1]*2, g.shape[0]*2), interpolation=cv2.INTER_LINEAR)
    g = cv2.bilateralFilter(g, 7, 50, 50)
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 13, 7)

def _prep_percentage_roi(crop: np.ndarray) -> np.ndarray:
    """Dedicated preprocessing for bottom-left percentage region."""
    import cv2
    h, w = crop.shape[:2]
    # 5x upscale
    big = cv2.resize(crop, (w*5, h*5), interpolation=cv2.INTER_CUBIC)
    g = _to_gray(big)
    
    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    cl = clahe.apply(g)
    
    # Adaptive threshold
    th = cv2.adaptiveThreshold(cl, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 9)
    
    # Sharpen
    sk = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]], dtype=np.float32)
    sh = np.clip(cv2.filter2D(th, -1, sk), 0, 255).astype(np.uint8)
    
    # Morphology close
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    return cv2.morphologyEx(sh, cv2.MORPH_CLOSE, k)

def _prep_summary_general(crop: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """For result/CGPA extraction."""
    import cv2
    h, w = crop.shape[:2]
    big = cv2.resize(crop, (w*3, h*3), interpolation=cv2.INTER_CUBIC)
    g = _to_gray(big)
    dn = cv2.bilateralFilter(g, 9, 75, 75)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4,4))
    cl = clahe.apply(dn)
    th1 = cv2.adaptiveThreshold(cl, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 19, 8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2,2))
    th1 = cv2.morphologyEx(th1, cv2.MORPH_CLOSE, k)
    sk = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]], dtype=np.float32)
    sh = np.clip(cv2.filter2D(th1, -1, sk), 0, 255).astype(np.uint8)
    _, th2 = cv2.threshold(dn, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    combined = cv2.bitwise_and(sh, th2)
    return combined, sh

# ─────────────────────────────────────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────────────────────────────────────

def _ocr(arr: np.ndarray, psm: int = 6, whitelist: str = "") -> Tuple[str, List[Dict]]:
    try:
        # import pytesseract
        from PIL import Image as PILImage
        cfg = f"--oem 3 --psm {psm}"
        if whitelist:
            cfg += f' -c tessedit_char_whitelist="{whitelist}"'
        pil = PILImage.fromarray(arr)
        text = pytesseract.image_to_string(pil, config=cfg, lang="eng")
        raw  = pytesseract.image_to_data(pil, config=cfg, lang="eng", output_type=pytesseract.Output.DICT)
        boxes = [
            {"text": (raw["text"][i] or "").strip(),
             "left": raw["left"][i], "top": raw["top"][i],
             "width": raw["width"][i], "height": raw["height"][i],
             "conf": int(raw["conf"][i])}
            for i in range(len(raw["text"]))
            if (raw["text"][i] or "").strip() and int(raw["conf"][i]) >= 0
        ]
        return text.strip(), boxes
    except Exception as exc:
        logger.error("[LAYOUT OCR] failed: %s", exc)
        return "", []

# ─────────────────────────────────────────────────────────────────────────────
# PRECISE NAME EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_NAME_ANCHOR = re.compile(r"candidate.?s\s+full\s+name|full\s+name\s*\(surname\s+first\)", re.I)
_NAME_REJECT_WORDS = {"figures", "marks", "obtained", "pass", "result", "grade", "total", "subject", "out", "percentage", "board", "university", "certificate"}
_GARBAGE_SYMS = re.compile(r"[{}\[\]|:;_=+~`<>@#^*\\\"\']")

def _valid_name(s: str) -> bool:
    s = s.strip()
    if len(s) < 5 or len(s) > 60: return False
    words = s.split()
    if len(words) < 2: return False
    # Reject if contains any numbers or percentages
    if re.search(r"[\d%]", s): return False
    # Reject if contains reject words
    if any(w.lower() in _NAME_REJECT_WORDS for w in words): return False
    # Must be mostly alphabetic
    alpha = sum(c.isalpha() or c == " " for c in s) / len(s)
    return alpha >= 0.85

def _clean_name(raw: str) -> str:
    cleaned = _GARBAGE_SYMS.sub(" ", raw)
    # Remove leading non-alpha
    cleaned = re.sub(r"^[^A-Za-z\u0900-\u097F]+", "", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned.title()

def _extract_name_by_anchor(text: str) -> Optional[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if _NAME_ANCHOR.search(line):
            # Extract exactly 1 line below anchor
            if i + 1 < len(lines):
                candidate = lines[i+1]
                cleaned = _clean_name(candidate)
                if _valid_name(cleaned):
                    logger.info("[NAME FOUND] Extracted 1 line below anchor: '%s' -> '%s'", candidate, cleaned)
                    return cleaned
    return None

# ─────────────────────────────────────────────────────────────────────────────
# ZONE A+B EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_BOARD_MAP = [
    (r"maharashtra\s+state\s+board|msbshse", "Maharashtra State Board"),
    (r"cbse|central\s+board",                "CBSE"),
    (r"icse|cisce",                          "ICSE"),
    (r"shivaji\s+university",                "Shivaji University, Kolhapur"),
    (r"savitribai\s+phule",                  "Savitribai Phule Pune University"),
    (r"mumbai\s+university",                 "University of Mumbai"),
    (r"nagpur\s+university",                 "Nagpur University"),
]
_YEAR_RE = re.compile(r"\b(20[0-2]\d)\b")

def _extract_from_header_text(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    low = text.lower()
    for pat, label in _BOARD_MAP:
        if re.search(pat, low):
            out["board"] = label
            break
    for m in _YEAR_RE.finditer(text):
        yr = int(m.group(1))
        if 2000 <= yr <= 2030:
            out["passing_year"] = yr
            break
    return out

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY & PERCENTAGE EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

_RESULT_MAP = [
    (r"\bfirst\s+class\s+with\s+distinction\b", "DISTINCTION"),
    (r"\bdistinction\b",   "DISTINCTION"),
    (r"\bpass(ed)?\b",     "PASS"),
    (r"\bfail(ed)?\b",     "FAIL"),
    (r"\bfirst\s+class\b", "FIRST CLASS"),
    (r"\bsecond\s+class\b","SECOND CLASS"),
    (r"\bthird\s+class\b", "THIRD CLASS"),
]

def _extract_result(text: str) -> Optional[str]:
    low = text.lower()
    for pat, label in _RESULT_MAP:
        if re.search(pat, low):
            return label
    return None

def _extract_cgpa(text: str) -> Optional[float]:
    m = re.search(r"cgpa\s*[:\-]?\s*(\d+(?:\.\d{1,2})?)", text, re.I)
    if not m:
        m = re.search(r"(\d+(?:\.\d{1,2})?)\s*cgpa", text, re.I)
    if m:
        v = float(m.group(1))
        if 0 < v <= 10:
            return round(v, 2)
    return None

def _extract_percentage_from_text(text: str) -> Optional[float]:
    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\b", text):
        v = float(f"{m.group(1)}.{m.group(2)}")
        if 0.0 <= v <= 100.0:
            return round(v, 2)
    return None

# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def extract_with_layout_engine(
    image_arr: np.ndarray,
    doc_id: str,
    doc_type: str = "hsc",
    full_text: str = "",
) -> Dict[str, Any]:
    logger.info("[LAYOUT ENGINE] Starting region extraction doc_id=%s type=%s", doc_id, doc_type)

    h, w = image_arr.shape[:2]
    zones = _segment_zones(image_arr)
    _save(image_arr if len(image_arr.shape) == 2 else image_arr[:,:,::-1], doc_id, "00_original")

    extracted: Dict[str, Any] = {}

    # ── ZONE A: Header ────────────────────────────────────────────────────────
    ya0, ya1 = zones["header"]
    crop_a = image_arr[ya0:ya1, :]
    proc_a = _prep_header(crop_a)
    _save(proc_a, doc_id, "01_zone_a_header")
    text_a, _ = _ocr(proc_a, psm=6)
    
    extracted.update(_extract_from_header_text(text_a))
    if full_text:
        fallback = _extract_from_header_text(full_text)
        for k in ("board", "passing_year"):
            if k not in extracted and k in fallback:
                extracted[k] = fallback[k]

    # ── ZONE B: Candidate Name (Strict Anchor-Based) ──────────────────────────
    yb0, yb1 = zones["candidate"]
    crop_b = image_arr[yb0:yb1, :]
    proc_b = _prep_candidate(crop_b)
    _save(proc_b, doc_id, "02_zone_b_candidate")
    text_b, _ = _ocr(proc_b, psm=6)
    
    cand_name = _extract_name_by_anchor(text_b)
    if not cand_name and full_text:
        cand_name = _extract_name_by_anchor(full_text)
    if cand_name:
        extracted["candidate_name"] = cand_name

    # ── ZONE D: Summary (Result & CGPA) ───────────────────────────────────────
    yd0, yd1 = zones["summary"]
    crop_d = image_arr[yd0:yd1, :]
    
    proc_d1, proc_d2 = _prep_summary_general(crop_d)
    text_d1, _ = _ocr(proc_d1, psm=6)
    text_d2, _ = _ocr(proc_d2, psm=6)
    combined_text = text_d1 + "\n" + text_d2

    res = _extract_result(combined_text)
    if not res and full_text:
        res = _extract_result(full_text)
    if res:
        extracted["result"] = res

    cgpa = _extract_cgpa(combined_text)
    if not cgpa and doc_type == "degree":
        cgpa = _extract_cgpa(full_text)
    if cgpa:
        extracted["cgpa"] = cgpa

    # ── ZONE P: Percentage ROI (Bottom-Left above QR) ─────────────────────────
    # Slice the left half of the summary zone to isolate percentage
    crop_pct = crop_d[:, :int(w * 0.45)]
    proc_pct = _prep_percentage_roi(crop_pct)
    _save(proc_pct, doc_id, "06_zone_p_percentage_roi")
    
    # OCR specifically tuned for percentages
    text_pct, _ = _ocr(proc_pct, psm=7, whitelist="0123456789.%")
    logger.debug("[ZONE P OCR]:\n%s", text_pct)
    
    pct = _extract_percentage_from_text(text_pct)
    if pct is not None:
        extracted["percentage"] = pct
        logger.info("[PERCENTAGE FOUND] ROI extraction: %.2f%%", pct)

    # ── Confidence ────────────────────────────────────────────────────────────
    score = 0.0
    if extracted.get("percentage"):    score += 0.40
    if extracted.get("result"):        score += 0.20
    if extracted.get("candidate_name"):score += 0.25
    if extracted.get("document_type"): score += 0.15
    extracted_conf = round(min(score, 1.0), 3)

    return {
        "extracted":   extracted,
        "confidence":  extracted_conf,
    }
