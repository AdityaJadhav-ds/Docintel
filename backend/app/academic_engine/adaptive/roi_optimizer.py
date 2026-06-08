"""
academic_engine/adaptive/roi_optimizer.py
==========================================
Multi-Preprocessing Ensemble + OCR Voting Engine.

For each crop variant, runs multiple preprocessing strategies in parallel
and collects OCR outputs from multiple engines / configurations.

Preprocessing variants:
  1. clahe        — CLAHE histogram equalization
  2. adaptive_thr — adaptive Gaussian threshold (binarize)
  3. sharpen      — unsharp-mask sharpening
  4. denoise      — fastNlMeans denoising
  5. morph_close  — morphological closing to join broken digits
  6. grayscale    — plain grayscale (baseline)
  7. invert       — inverted (for dark backgrounds)

OCR engines per field:
  Percentage/CGPA:   Tesseract PSM 7 (single line) + whitelist
  Name/Result:       Tesseract PSM 7 (single line) + EasyOCR
  Block (header):    Tesseract PSM 6 (block) + EasyOCR

Voting:
  - Run all preprocessed images through all relevant engines
  - Collect (text, confidence, preprocessing, engine) tuples
  - Validate each text against the field's validator
  - Return highest-confidence valid result

Output:
  OcrEnsembleResult — winner text, confidence, winning strategy details,
                      and full ranked candidate list for debug export.
"""

from __future__ import annotations

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.logger import logger

# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class OcrCandidate:
    text:           str
    confidence:     float
    preprocessing:  str
    engine:         str
    valid:          bool = False

    def __repr__(self) -> str:
        return (
            f"OcrCandidate({self.text!r}, conf={self.confidence:.2f}, "
            f"pre={self.preprocessing!r}, eng={self.engine!r}, valid={self.valid})"
        )


@dataclass
class OcrEnsembleResult:
    field:          str
    winner:         Optional[OcrCandidate] = None
    all_candidates: List[OcrCandidate] = field(default_factory=list)
    recovered:      bool = False
    recovery_note:  str  = ""

    @property
    def text(self) -> str:
        return self.winner.text if self.winner else ""

    @property
    def confidence(self) -> float:
        return self.winner.confidence if self.winner else 0.0

    @property
    def found(self) -> bool:
        return self.winner is not None and bool(self.winner.text)


# ── Preprocessing strategies ──────────────────────────────────────────────────

def _to_gray(bgr: np.ndarray) -> np.ndarray:
    if len(bgr.shape) == 2:
        return bgr
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


def _prep_clahe(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _prep_adaptive_thr(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        blockSize=15, C=4,
    )


def _prep_sharpen(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    return cv2.addWeighted(gray, 1.6, blur, -0.6, 0)


def _prep_denoise(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    return cv2.fastNlMeansDenoising(gray, h=15)


def _prep_morph_close(bgr: np.ndarray) -> np.ndarray:
    gray = _prep_adaptive_thr(bgr)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(gray, cv2.MORPH_CLOSE, k)


def _prep_grayscale(bgr: np.ndarray) -> np.ndarray:
    return _to_gray(bgr)


def _prep_invert(bgr: np.ndarray) -> np.ndarray:
    gray = _to_gray(bgr)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return bw


_PREPROCESSING_STRATEGIES: Dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "clahe":        _prep_clahe,
    "adaptive_thr": _prep_adaptive_thr,
    "sharpen":      _prep_sharpen,
    "denoise":      _prep_denoise,
    "morph_close":  _prep_morph_close,
    "grayscale":    _prep_grayscale,
    "invert":       _prep_invert,
}


# ── Upscaling helper ──────────────────────────────────────────────────────────

def _upscale(gray: np.ndarray, min_w: int = 400) -> np.ndarray:
    h, w = gray.shape[:2]
    if w < min_w:
        scale = min_w / w
        return cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    return gray


# ── Tesseract OCR runner ──────────────────────────────────────────────────────

def _tess_ocr(img: np.ndarray, config: str) -> Tuple[str, float]:
    try:
        # import pytesseract
        data = pytesseract.image_to_data(
            img, config=config, lang="eng",
            output_type=pytesseract.Output.DICT,
        )
        text = pytesseract.image_to_string(img, config=config, lang="eng").strip()
        confs = [c for c in data["conf"] if isinstance(c, (int, float)) and c > 0]
        conf = (sum(confs) / len(confs) / 100.0) if confs else 0.2
        return text, conf
    except Exception as exc:
        logger.debug("[roi_optimizer] Tesseract failed: %s", exc)
        return "", 0.0


def _easyocr(bgr: np.ndarray) -> Tuple[str, float]:
    try:
        from app.academic_engine.ocr.hybrid_ocr import _run_easyocr
        r = _run_easyocr(bgr)
        return r.get("text", ""), r.get("confidence", 0.0)
    except Exception as exc:
        logger.debug("[roi_optimizer] EasyOCR failed: %s", exc)
        return "", 0.0


# ── OCR config per field ──────────────────────────────────────────────────────

_FIELD_CONFIGS: Dict[str, List[Dict]] = {
    "percentage": [
        {"engine": "tess_psm7",  "config": "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.%"},
        {"engine": "tess_psm6",  "config": "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789.%"},
        {"engine": "tess_psm13", "config": "--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789.%"},
    ],
    "cgpa": [
        {"engine": "tess_psm7",  "config": "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789."},
        {"engine": "tess_psm6",  "config": "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789."},
    ],
    "result": [
        {"engine": "tess_psm7",  "config": "--oem 3 --psm 7"},
        {"engine": "easyocr",    "config": ""},
    ],
    "candidate": [
        {"engine": "tess_psm7",  "config": "--oem 3 --psm 7"},
        {"engine": "tess_psm6",  "config": "--oem 3 --psm 6"},
        {"engine": "easyocr",    "config": ""},
    ],
    "default": [
        {"engine": "tess_psm6",  "config": "--oem 3 --psm 6"},
        {"engine": "easyocr",    "config": ""},
    ],
}


# ── Validators ────────────────────────────────────────────────────────────────

def _validate_percentage(text: str) -> bool:
    m = re.search(r'\d{1,3}(?:\.\d{1,2})?', text)
    if m:
        try:
            v = float(m.group())
            return 0.0 < v <= 100.0
        except ValueError:
            pass
    return False


def _validate_cgpa(text: str) -> bool:
    m = re.search(r'\d{1,2}(?:\.\d{1,2})?', text)
    if m:
        try:
            v = float(m.group())
            return 0.0 < v <= 10.0
        except ValueError:
            pass
    return False


_RESULT_KEYWORDS = {
    "PASS", "FAIL", "DISTINCTION", "FIRST", "SECOND", "THIRD",
    "CLASS", "COMPARTMENT", "ABSENT", "WITHHELD", "PASSED", "FAILED",
}

def _validate_result(text: str) -> bool:
    clean = re.sub(r'[^A-Za-z\s]', '', text).upper()
    return any(kw in clean for kw in _RESULT_KEYWORDS)


def _validate_name(text: str) -> bool:
    clean = re.sub(r'[^A-Za-z\s]', '', text).strip()
    words = clean.split()
    return 2 <= len(words) <= 6 and all(len(w) >= 2 for w in words)


_VALIDATORS: Dict[str, Callable[[str], bool]] = {
    "percentage": _validate_percentage,
    "cgpa":       _validate_cgpa,
    "result":     _validate_result,
    "candidate":  _validate_name,
    "default":    lambda t: bool(t.strip()),
}


# ── Main optimizer ────────────────────────────────────────────────────────────

class ROIOptimizer:
    """
    Runs multi-preprocessing × multi-engine OCR ensemble on a crop image.
    Returns the highest-confidence valid result across all combinations.
    """

    def optimize(
        self,
        crop:  np.ndarray,        # BGR image
        field: str,               # "percentage" | "cgpa" | "result" | "candidate"
        preprocessing_names: Optional[List[str]] = None,
        use_easyocr: bool = True,
    ) -> OcrEnsembleResult:
        """
        Run ensemble OCR on a single crop.

        Args:
            crop:               BGR numpy array to OCR.
            field:              Field name for engine/validator selection.
            preprocessing_names: Subset of preprocessing strategies to use.
                                 None = use all.
            use_easyocr:        Whether to include EasyOCR in ensemble.

        Returns:
            OcrEnsembleResult with winner + all candidates for debug.
        """
        if crop is None or crop.size == 0:
            return OcrEnsembleResult(field=field)

        result = OcrEnsembleResult(field=field)
        validator = _VALIDATORS.get(field, _VALIDATORS["default"])
        engine_specs = _FIELD_CONFIGS.get(field, _FIELD_CONFIGS["default"])

        # Build preprocessing list
        prep_names = preprocessing_names or list(_PREPROCESSING_STRATEGIES.keys())

        for prep_name in prep_names:
            prep_fn = _PREPROCESSING_STRATEGIES.get(prep_name)
            if prep_fn is None:
                continue

            try:
                processed = prep_fn(crop)
                processed = _upscale(processed, min_w=350)
            except Exception as exc:
                logger.debug("[roi_optimizer] prep=%s failed: %s", prep_name, exc)
                continue

            for spec in engine_specs:
                engine_name = spec["engine"]
                config      = spec["config"]

                # Skip EasyOCR if disabled
                if engine_name == "easyocr" and not use_easyocr:
                    continue

                try:
                    if engine_name == "easyocr":
                        # EasyOCR needs BGR
                        if len(processed.shape) == 2:
                            bgr_in = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)
                        else:
                            bgr_in = crop
                        text, conf = _easyocr(bgr_in)
                    else:
                        text, conf = _tess_ocr(processed, config)
                except Exception:
                    continue

                if not text.strip():
                    continue

                valid = validator(text)
                candidate = OcrCandidate(
                    text          = text.strip(),
                    confidence    = conf,
                    preprocessing = prep_name,
                    engine        = engine_name,
                    valid         = valid,
                )
                result.all_candidates.append(candidate)
                logger.debug("[roi_optimizer] field=%-15s pre=%-15s eng=%-12s valid=%s text=%r conf=%.2f",
                             field, prep_name, engine_name, valid, text[:40], conf)

        # Pick winner: prefer valid + highest confidence; fall back to highest confidence
        valid_candidates   = [c for c in result.all_candidates if c.valid]
        invalid_candidates = [c for c in result.all_candidates if not c.valid]

        if valid_candidates:
            result.winner = max(valid_candidates, key=lambda c: c.confidence)
        elif invalid_candidates:
            # Return best-effort for upstream recovery
            result.winner = max(invalid_candidates, key=lambda c: c.confidence)

        if result.winner:
            logger.info(
                "[roi_optimizer] field=%-15s winner=%r conf=%.2f pre=%s eng=%s valid=%s",
                field, result.winner.text[:30], result.winner.confidence,
                result.winner.preprocessing, result.winner.engine, result.winner.valid,
            )
        else:
            logger.info("[roi_optimizer] field=%-15s — no candidates", field)

        return result


# ── Singleton ─────────────────────────────────────────────────────────────────
_optimizer = ROIOptimizer()


def optimize_roi_ocr(
    crop: np.ndarray,
    field: str,
    preprocessing_names: Optional[List[str]] = None,
    use_easyocr: bool = True,
) -> OcrEnsembleResult:
    """Module-level wrapper."""
    return _optimizer.optimize(crop, field, preprocessing_names, use_easyocr)
