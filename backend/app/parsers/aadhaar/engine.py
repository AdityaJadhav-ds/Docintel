"""
app/parsers/aadhaar/engine.py — Dedicated Aadhaar Intelligence Engine v4
=========================================================================
Completely independent from the universal OCR parser.

Pipeline:
  1. Preprocess image (orientation fix → skew → CLAHE → denoise → sharpen)
  2. Crop named regions per card layout knowledge
  3. Run multi-pass OCR per region × image variant
  4. Filter Hindi lines, apply confidence threshold
  5. Extract each field using regex + validation rules
  6. Vote across OCR passes → best candidate wins
  7. Score overall confidence
  8. Return structured result + debug overlay option

If no image is available (PDF/text-only path):
  - Falls back to the v3 text-based parser with all improvements applied
  - Never returns garbage; returns None with low confidence instead

Target accuracy:
  - Name:    >95% on clean scans, >85% on mobile photos
  - DOB:     >98%
  - Number:  >99%
  - Gender:  >97%
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Any

from app.core.logger import logger
from .preprocessor import preprocess_aadhaar
from .layout import get_regions
from .ocr_runner import ocr_field_variants, ocr_full_card
from .extractor import (
    extract_aadhaar_number,
    extract_dob,
    extract_gender,
    extract_name,
)
from .validator import validate_name


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED RESULT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _make_field(value: Optional[str], confidence: float) -> Dict:
    return {"value": value, "confidence": round(confidence, 3)}


def _make_empty_result(reason: str = "unknown") -> Dict:
    return {
        "name":           _make_field(None, 0.0),
        "aadhaar_number": _make_field(None, 0.0),
        "dob":            _make_field(None, 0.0),
        "gender":         _make_field(None, 0.0),
        "confidence":     0.0,
        "debug": {"reason": reason},
        # Legacy flat keys (for backwards-compat with existing API callers)
        "_name":           None,
        "_aadhaar_number": None,
        "_dob":            None,
    }


def _flatten(result: Dict) -> Dict:
    """Add flat legacy keys alongside the structured ones."""
    result["_name"]           = result["name"]["value"]
    result["_aadhaar_number"] = result["aadhaar_number"]["value"]
    result["_dob"]            = result["dob"]["value"]
    result["_gender"]         = result["gender"]["value"]
    return result


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE-BASED PATH (primary)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_from_image(img) -> Dict:
    """
    Full pipeline when a numpy image array is available.
    """
    import numpy as np

    # Step 1: Preprocess — returns dict of variants
    logger.info("[aadhaar_v4] Starting image-based extraction")
    variants = preprocess_aadhaar(img, correct_orientation=True)
    logger.debug("[aadhaar_v4] Variants ready: %s", list(variants.keys()))

    # Step 2: Crop regions for each variant
    # regions_by_variant: {variant_name: {region_name: np.ndarray}}
    regions_by_variant: Dict[str, Dict[str, Any]] = {}
    for variant_name, arr in variants.items():
        regions_by_variant[variant_name] = get_regions(arr)

    # Step 3 + 4: Per-field multi-pass OCR

    # Aadhaar number — PSM 7 (single line) primary, wider region
    num_candidates = ocr_field_variants(
        regions_by_variant, "number",
        psm_modes=(7, 6, 4),
        filter_hindi=True,
    )
    num_candidates += ocr_field_variants(
        regions_by_variant, "number_wide",
        psm_modes=(7, 6),
        filter_hindi=True,
    )

    # DOB — PSM 7 primary
    dob_candidates = ocr_field_variants(
        regions_by_variant, "dob",
        psm_modes=(7, 6, 4),
        filter_hindi=True,
    )
    dob_candidates += ocr_field_variants(
        regions_by_variant, "dob_full",
        psm_modes=(6, 4),
        filter_hindi=True,
    )

    # Gender — use DOB region (gender is usually on the same line)
    gender_candidates = dob_candidates + ocr_field_variants(
        regions_by_variant, "gender",
        psm_modes=(7, 6),
        filter_hindi=True,
    )

    # Name — PSM 4 primary (single column), Hindi filtered
    name_candidates = ocr_field_variants(
        regions_by_variant, "name",
        psm_modes=(4, 6, 7, 11),
        filter_hindi=True,
    )
    name_candidates += ocr_field_variants(
        regions_by_variant, "name_full",
        psm_modes=(4, 6, 7),
        filter_hindi=True,
    )

    # Also include full-card OCR as fallback source
    full_card_results = ocr_full_card(variants)
    full_card_texts = [text for text, _ in full_card_results]
    name_candidates  += full_card_texts
    dob_candidates   += full_card_texts
    num_candidates   += full_card_texts

    logger.debug("[aadhaar_v4] Candidate counts — name:%d dob:%d number:%d gender:%d",
                 len(name_candidates), len(dob_candidates),
                 len(num_candidates), len(gender_candidates))

    # Step 5 + 6: Extract + vote
    aadhaar_number, num_conf  = extract_aadhaar_number(num_candidates)
    dob,            dob_conf  = extract_dob(dob_candidates)
    gender,         gen_conf  = extract_gender(gender_candidates)
    name,           name_conf = extract_name(
        name_candidates,
        dob_found=dob,
        gender_found=gender,
    )

    return aadhaar_number, num_conf, dob, dob_conf, gender, gen_conf, name, name_conf


# ─────────────────────────────────────────────────────────────────────────────
# TEXT-ONLY FALLBACK PATH (PDF / no image)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_from_text(ocr_text: str, variant_texts: Optional[Dict[str, str]] = None) -> Dict:
    """
    When no image is available: delegate to the improved text-based parser.
    We use the legacy aadhaar_parser but with additional post-processing.
    """
    try:
        from app.parsers.aadhaar_parser import parse_aadhaar as parse_v3
        result_v3 = parse_v3(ocr_text, variant_texts=variant_texts, image_gray=None)
        return result_v3
    except Exception as e:
        logger.error("[aadhaar_v4] Text fallback failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def parse_aadhaar_v4(
    ocr_text: str = "",
    variant_texts: Optional[Dict[str, str]] = None,
    image_gray=None,          # np.ndarray BGR or grayscale
    debug: bool = False,
) -> Dict:
    """
    Main Aadhaar extraction entry point.

    Args:
        ocr_text:      Full-card OCR text (from any engine)
        variant_texts: {variant_name: ocr_text} for multi-variant voting
        image_gray:    numpy image array (BGR or grayscale).
                       If provided, image-based region OCR is used (preferred).
        debug:         If True, include debug overlay info in result.

    Returns:
        {
          "name":           {"value": str|None, "confidence": float},
          "aadhaar_number": {"value": str|None, "confidence": float},
          "dob":            {"value": str|None, "confidence": float},
          "gender":         {"value": str|None, "confidence": float},
          "confidence":     float,             # overall 0-1
          "debug":          {...},
          # Legacy flat keys (backwards-compat)
          "_name":           str|None,
          "_aadhaar_number": str|None,
          "_dob":            str|None,
          "_gender":         str|None,
          # Legacy keys expected by existing callers
          "field_confidences": {"name": int, "aadhaar_number": int, "dob": int}
        }
    """
    logger.info("[aadhaar_v4] parse_aadhaar_v4 called — has_image=%s text_len=%d",
                image_gray is not None, len(ocr_text or ""))

    if image_gray is not None:
        try:
            (
                aadhaar_number, num_conf,
                dob, dob_conf,
                gender, gen_conf,
                name, name_conf,
            ) = _parse_from_image(image_gray)
        except Exception as e:
            logger.error("[aadhaar_v4] Image pipeline failed, falling back to text: %s", e)
            aadhaar_number = num_conf = dob = dob_conf = gender = gen_conf = name = name_conf = None
            name_conf = dob_conf = num_conf = gen_conf = 0.0

        # If image pipeline produced nothing, also try text-based path and merge
        if not name and ocr_text:
            logger.info("[aadhaar_v4] Image path found no name — augmenting with text path")
            text_result = _parse_from_text(ocr_text, variant_texts)
            if text_result:
                if not name:
                    name = text_result.get("name")
                    name_conf = text_result.get("field_confidences", {}).get("name", 0) / 100.0
                if not dob:
                    dob = text_result.get("dob")
                    dob_conf = text_result.get("field_confidences", {}).get("dob", 0) / 100.0
                if not aadhaar_number:
                    aadhaar_number = text_result.get("aadhaar_number")
                    num_conf = text_result.get("field_confidences", {}).get("aadhaar_number", 0) / 100.0

    else:
        # Text-only path
        logger.info("[aadhaar_v4] No image — using text-only path")
        text_result = _parse_from_text(ocr_text, variant_texts)
        if text_result is None:
            return _flatten(_make_empty_result("text_parse_failed"))

        name           = text_result.get("name")
        name_conf      = text_result.get("field_confidences", {}).get("name", 0) / 100.0
        aadhaar_number = text_result.get("aadhaar_number")
        num_conf       = text_result.get("field_confidences", {}).get("aadhaar_number", 0) / 100.0
        dob            = text_result.get("dob")
        dob_conf       = text_result.get("field_confidences", {}).get("dob", 0) / 100.0
        gender         = None
        gen_conf       = 0.0

    # Compute overall confidence
    found_count = sum([
        name is not None,
        aadhaar_number is not None,
        dob is not None,
    ])
    field_confs = [num_conf, dob_conf, name_conf]
    overall_conf = round(sum(field_confs) / max(len(field_confs), 1), 4) if found_count else 0.0

    result = {
        "name":           _make_field(name, name_conf),
        "aadhaar_number": _make_field(aadhaar_number, num_conf),
        "dob":            _make_field(dob, dob_conf),
        "gender":         _make_field(gender, gen_conf),
        "confidence":     overall_conf,
        "debug": {
            "image_path": image_gray is not None,
            "fields_found": found_count,
        },
        # Legacy flat keys (used by existing API response builders)
        "_name":           name,
        "_aadhaar_number": aadhaar_number,
        "_dob":            dob,
        "_gender":         gender,
        # Legacy field_confidences dict (0-100 scale)
        "field_confidences": {
            "name":           round(name_conf * 100),
            "aadhaar_number": round(num_conf * 100),
            "dob":            round(dob_conf * 100),
        },
    }

    logger.info(
        "[aadhaar_v4] Result — name=%r dob=%r aadhaar=%s gender=%r overall_conf=%.2f",
        name, dob, aadhaar_number, gender, overall_conf,
    )

    return result
