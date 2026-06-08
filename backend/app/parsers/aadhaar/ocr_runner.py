"""
app/parsers/aadhaar/ocr_runner.py — Multi-pass regional OCR for Aadhaar
=======================================================================
Runs Tesseract on each named region with:
  - Multiple PSM modes per region
  - Multiple preprocessed image variants
  - Per-word confidence filtering
  - Hindi line isolation (script detection)
  - Returns raw text + confidence scores per region
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.core.logger import logger
from . import rules as R


# ─────────────────────────────────────────────────────────────────────────────
# TESSERACT WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

def _get_tess_cmd() -> Optional[str]:
    try:
        from app.core.config import config
        import os, shutil
        path = config.TESSERACT_PATH
        if os.path.isfile(path):
            return path
        return shutil.which("tesseract")
    except Exception:
        import shutil
        return shutil.which("tesseract")


def _tess_string(arr: np.ndarray, psm: int = 6, lang: str = "eng") -> str:
    """Run Tesseract image_to_string."""
    try:
        # import pytesseract
        from PIL import Image
        cmd = _get_tess_cmd()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        cfg = f"--oem 3 --psm {psm}"
        pil = Image.fromarray(arr)
        return pytesseract.image_to_string(pil, config=cfg, lang=lang).strip()
    except Exception as e:
        logger.debug("[aadhaar_ocr] tess_string psm=%d failed: %s", psm, e)
        return ""


def _tess_data(arr: np.ndarray, psm: int = 6, lang: str = "eng") -> List[Dict]:
    """
    Run Tesseract image_to_data and return list of word records with
    confidence, text, and bounding box.
    """
    try:
        # import pytesseract
        from PIL import Image
        cmd = _get_tess_cmd()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        cfg = f"--oem 3 --psm {psm}"
        pil = Image.fromarray(arr)
        data = pytesseract.image_to_data(
            pil, config=cfg, lang=lang,
            output_type=pytesseract.Output.DICT
        )
        records = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            if not text:
                continue
            conf = data["conf"][i]
            try:
                conf_f = float(conf)
            except (ValueError, TypeError):
                conf_f = -1.0
            records.append({
                "text": text,
                "conf": conf_f,
                "left": data["left"][i],
                "top":  data["top"][i],
                "width": data["width"][i],
                "height": data["height"][i],
            })
        return records
    except Exception as e:
        logger.debug("[aadhaar_ocr] tess_data psm=%d failed: %s", psm, e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPT DETECTION — separate Hindi (Devanagari) from English lines
# ─────────────────────────────────────────────────────────────────────────────

# Unicode ranges for Devanagari (Hindi)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# High ratio of non-ASCII chars => likely Hindi line
def _is_hindi_line(text: str, threshold: float = 0.30) -> bool:
    """Return True if more than `threshold` fraction of chars are non-ASCII."""
    if not text:
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text) > threshold


def _filter_english_lines(text: str) -> str:
    """
    Remove lines that appear to be Hindi/Devanagari and keep only
    English lines. This is the key multilingual isolation step.
    """
    lines = text.splitlines()
    english_lines = []
    for line in lines:
        if _DEVANAGARI_RE.search(line):
            logger.debug("[aadhaar_ocr] Hindi line removed: %r", line[:60])
            continue
        if _is_hindi_line(line):
            logger.debug("[aadhaar_ocr] Non-ASCII heavy line removed: %r", line[:60])
            continue
        english_lines.append(line)
    return "\n".join(english_lines)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE FILTER
# ─────────────────────────────────────────────────────────────────────────────

def _high_conf_text(records: List[Dict], min_conf: float = R.MIN_OCR_CONF * 100) -> str:
    """
    Reconstruct text using only words above confidence threshold.
    Groups by (block_num, par_num, line_num) to preserve line structure.
    """
    accepted = [r["text"] for r in records if r["conf"] >= min_conf and r["text"].strip()]
    return " ".join(accepted)


def _conf_stats(records: List[Dict]) -> Tuple[float, float]:
    """Return (mean_conf, min_conf) for a set of word records."""
    confs = [r["conf"] for r in records if r["conf"] >= 0]
    if not confs:
        return 0.0, 0.0
    return float(np.mean(confs)), float(np.min(confs))


# ─────────────────────────────────────────────────────────────────────────────
# REGION OCR — run multiple PSM modes and pick best result
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_region_multipass(
    arr: np.ndarray,
    psm_modes: Tuple[int, ...],
    lang: str = "eng",
    filter_hindi: bool = True,
    min_conf: float = R.MIN_OCR_CONF * 100,
) -> List[Tuple[str, float]]:
    """
    Run OCR with multiple PSM modes on one region.

    Returns:
        List of (text, mean_confidence) sorted by descending confidence.
        text is English-only (Hindi lines filtered if filter_hindi=True).
    """
    results: List[Tuple[str, float]] = []

    for psm in psm_modes:
        records = _tess_data(arr, psm=psm, lang=lang)
        if not records:
            # Fall back to string mode
            raw = _tess_string(arr, psm=psm, lang=lang)
            if raw:
                text = _filter_english_lines(raw) if filter_hindi else raw
                results.append((text.strip(), 50.0))  # unknown confidence
            continue

        mean_c, _ = _conf_stats(records)

        # Full text (all words)
        full_text = _filter_english_lines(
            " ".join(r["text"] for r in records if r["text"].strip())
        ) if filter_hindi else " ".join(r["text"] for r in records if r["text"].strip())

        # High-confidence text only
        hc_text = _filter_english_lines(
            _high_conf_text(records, min_conf=min_conf)
        ) if filter_hindi else _high_conf_text(records, min_conf=min_conf)

        if hc_text.strip():
            results.append((hc_text.strip(), mean_c))
        elif full_text.strip():
            results.append((full_text.strip(), mean_c * 0.7))

    # Sort by descending confidence
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-VARIANT OCR ACROSS IMAGE PREPROCESSED VERSIONS
# ─────────────────────────────────────────────────────────────────────────────

def ocr_field_variants(
    regions_by_variant: Dict[str, Dict[str, np.ndarray]],
    field_name: str,
    psm_modes: Tuple[int, ...] = (4, 6, 7),
    filter_hindi: bool = True,
) -> List[str]:
    """
    For a named field, run OCR across all image variants and collect
    all candidate text strings (deduped, ordered by quality).

    Args:
        regions_by_variant: {variant_name: {field_name: np.ndarray}}
        field_name:         e.g. "name", "dob", "number"
        psm_modes:          Tesseract PSM modes to try per variant
        filter_hindi:       strip Devanagari lines

    Returns:
        Ordered list of candidate strings (best first).
    """
    all_candidates: List[Tuple[str, float]] = []

    for variant_name, regions in regions_by_variant.items():
        arr = regions.get(field_name)
        if arr is None or arr.size == 0:
            continue
        results = _ocr_region_multipass(arr, psm_modes=psm_modes, filter_hindi=filter_hindi)
        for text, conf in results:
            if text.strip():
                all_candidates.append((text.strip(), conf))
        logger.debug("[aadhaar_ocr] %s/%s → %d results", variant_name, field_name,
                     len(results))

    # Sort globally by confidence desc
    all_candidates.sort(key=lambda x: x[1], reverse=True)

    # Return deduped list (preserve order)
    seen: set = set()
    ordered: List[str] = []
    for text, _ in all_candidates:
        norm = re.sub(r"\s+", " ", text.lower().strip())
        if norm and norm not in seen:
            seen.add(norm)
            ordered.append(text.strip())

    return ordered


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: full card text from all variants
# ─────────────────────────────────────────────────────────────────────────────

def ocr_full_card(preprocessed_variants: Dict[str, np.ndarray]) -> List[Tuple[str, float]]:
    """
    Run full-card OCR on all preprocessed variants.
    Returns list of (full_text, mean_confidence).
    """
    results: List[Tuple[str, float]] = []
    for variant_name, arr in preprocessed_variants.items():
        for psm in (4, 6, 3):
            records = _tess_data(arr, psm=psm, lang="eng")
            if records:
                full = "\n".join(r["text"] for r in records if r["text"].strip())
                filtered = _filter_english_lines(full)
                mean_c, _ = _conf_stats(records)
                if filtered.strip():
                    results.append((filtered.strip(), mean_c))
                    break
    results.sort(key=lambda x: x[1], reverse=True)
    return results
