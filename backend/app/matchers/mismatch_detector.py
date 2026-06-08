"""
app/matchers/mismatch_detector.py — Validation result engine v2
================================================================
Produces the required enhanced output format:
{
  "field": "name",
  "stored": "Nikita Bhagvan Jadhav",
  "extracted": "Nikita Bhagwan Jadhav",
  "match_score": 94,
  "status": "POSSIBLE_MATCH",
  "confidence": 96,
  "reason": "minor OCR variation in: Bhagvan"
}
"""

from __future__ import annotations
from typing import List, Dict, Optional
from app.core.logger import logger
from app.matchers.matcher import match_name, match_id, match_dob
from app.ocr.confidence_engine import calculate_field_confidence


# ── Status constants ──────────────────────────────────────────────────────────

class ValidationStatus:
    VERIFIED          = "VERIFIED"
    POSSIBLE_MISMATCH = "POSSIBLE_MISMATCH"
    MISMATCH          = "MISMATCH"
    OCR_FAILED        = "OCR_FAILED"
    DOC_TYPE_UNKNOWN  = "DOC_TYPE_UNKNOWN"


def _build_field_result(
    field: str,
    stored: Optional[str],
    extracted: Optional[str],
    match_result: Dict,
    field_confidence: int,
) -> Dict:
    """Build the required output format for a single field."""
    return {
        "field":       field,
        "stored":      stored,
        "extracted":   extracted,
        "match_score": match_result.get("score", 0),
        "status":      match_result.get("status", "MISMATCH"),
        "confidence":  field_confidence,
        "reason":      match_result.get("reason", ""),
    }


def build_validation_result(
    doc_type: str,
    stored_user: Dict,
    extracted: Dict,
    ocr_confidence: float,
    variant_texts: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Compare stored user data vs extracted OCR data field-by-field.

    Args:
        doc_type:       'aadhaar' | 'pan' | 'unknown'
        stored_user:    Supabase user record {full_name, dob, ...}
        extracted:      Output of aadhaar_parser or pan_parser
        ocr_confidence: Overall OCR pipeline confidence (0-1)
        variant_texts:  OCR variant texts for confidence scoring

    Returns:
        Full validation result with enhanced field-level output.
    """

    if doc_type == "unknown":
        return {
            "overall_status": ValidationStatus.DOC_TYPE_UNKNOWN,
            "doc_type":       doc_type,
            "fields":         [],
            "ocr_confidence": ocr_confidence,
            "summary":        "Document type could not be determined.",
        }

    # Check for empty extraction
    has_data = any(v for k, v in extracted.items()
                   if k not in ("confidence", "field_confidences") and v)
    if not has_data and ocr_confidence == 0.0:
        return {
            "overall_status": ValidationStatus.OCR_FAILED,
            "doc_type":       doc_type,
            "fields":         [],
            "ocr_confidence": ocr_confidence,
            "summary":        "OCR extraction produced no usable data.",
        }

    # Per-field confidences from parser (0-100 scale)
    fc = extracted.get("field_confidences", {})
    vt = variant_texts or {}

    fields:   List[Dict] = []
    statuses: List[str]  = []

    # ── Name ──────────────────────────────────────────────────────────────────
    stored_name    = stored_user.get("full_name") or stored_user.get("name")
    extracted_name = extracted.get("name")
    name_match     = match_name(stored_name, extracted_name)
    name_conf      = fc.get("name") or calculate_field_confidence("name", extracted_name, "", vt)
    fields.append(_build_field_result("name", stored_name, extracted_name, name_match, name_conf))
    statuses.append(name_match["status"])

    # ── DOB ───────────────────────────────────────────────────────────────────
    stored_dob    = stored_user.get("dob")
    extracted_dob = extracted.get("dob")
    dob_match     = match_dob(stored_dob, extracted_dob)
    dob_conf      = fc.get("dob") or calculate_field_confidence("dob", extracted_dob, "", vt)
    fields.append(_build_field_result("dob", stored_dob, extracted_dob, dob_match, dob_conf))
    statuses.append(dob_match["status"])

    # ── ID Number ─────────────────────────────────────────────────────────────
    if doc_type == "aadhaar":
        stored_id    = stored_user.get("aadhaar_number")
        extracted_id = extracted.get("aadhaar_number")
        id_match     = match_id(stored_id, extracted_id)
        id_conf      = fc.get("aadhaar_number") or calculate_field_confidence("aadhaar_number", extracted_id, "", vt)
        fields.append(_build_field_result("aadhaar_number", stored_id, extracted_id, id_match, id_conf))
        statuses.append(id_match["status"])
    elif doc_type == "pan":
        stored_id    = stored_user.get("pan_number")
        extracted_id = extracted.get("pan_number")
        id_match     = match_id(stored_id, extracted_id)
        id_conf      = fc.get("pan_number") or calculate_field_confidence("pan_number", extracted_id, "", vt)
        fields.append(_build_field_result("pan_number", stored_id, extracted_id, id_match, id_conf))
        statuses.append(id_match["status"])

    # ── Overall status ────────────────────────────────────────────────────────
    if "MISMATCH" in statuses:
        overall = ValidationStatus.MISMATCH
    elif "POSSIBLE_MATCH" in statuses:
        overall = ValidationStatus.POSSIBLE_MISMATCH
    else:
        overall = ValidationStatus.VERIFIED

    mismatched = [f["field"] for f in fields if f["status"] == "MISMATCH"]
    possible   = [f["field"] for f in fields if f["status"] == "POSSIBLE_MATCH"]

    if overall == ValidationStatus.VERIFIED:
        summary = "All fields verified successfully."
    elif overall == ValidationStatus.POSSIBLE_MISMATCH:
        summary = f"Possible mismatch in: {', '.join(possible)}. Manual review recommended."
    else:
        summary = f"Mismatch detected in: {', '.join(mismatched)}."

    result = {
        "overall_status": overall,
        "doc_type":       doc_type,
        "fields":         fields,
        "ocr_confidence": ocr_confidence,
        "summary":        summary,
    }

    logger.info("[mismatch_detector] overall=%s fields=%s", overall, statuses)
    return result
