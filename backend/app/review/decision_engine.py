"""
app/review/decision_engine.py — Validation decision engine
============================================================
decide_validation_status() is the single entry point.

Wraps approval_rules.evaluate_rules() and enriches output with:
  - side-by-side comparison payload
  - difference type classification
  - recommended action per field
"""

from __future__ import annotations
from typing import Dict, List, Optional
from app.core.logger import logger
from app.review.approval_rules import evaluate_rules, RuleResult


# ── Difference type classifier ────────────────────────────────────────────────

def _classify_difference(field: str, stored: Optional[str], extracted: Optional[str],
                          status: str, score: float) -> str:
    """
    Returns a human-readable difference_type for the comparison payload.
    """
    if status == "MATCH":
        return "exact_match"
    if stored is None or extracted is None:
        return "missing_value"
    if status == "POSSIBLE_MATCH":
        if score >= 90:
            return "minor_ocr_variation"
        if score >= 80:
            return "spelling_variation"
        return "word_order_variation"
    # MISMATCH
    if field in ("aadhaar_number", "pan_number"):
        return "id_number_mismatch"
    if field == "dob":
        return "date_mismatch"
    if field == "name":
        if score >= 50:
            return "significant_name_difference"
        return "completely_different_name"
    return "field_mismatch"


def _recommended_action(status: str, diff_type: str, score: float) -> str:
    """Return a recommended action string for each field."""
    if status == "MATCH":
        return "no_action"
    if diff_type == "minor_ocr_variation":
        return "auto_correct_suggested"
    if diff_type in ("spelling_variation", "word_order_variation"):
        return "manual_review"
    if diff_type == "missing_value":
        return "re_upload_document"
    if diff_type in ("id_number_mismatch", "completely_different_name", "date_mismatch"):
        return "reject_document"
    return "manual_review"


def build_comparison_payload(fields: List[Dict]) -> List[Dict]:
    """
    Build side-by-side comparison payload for each field.
    """
    result = []
    for f in fields:
        field     = f.get("field", "")
        stored    = f.get("stored")
        extracted = f.get("extracted")
        status    = f.get("status", "MISMATCH")
        score     = f.get("match_score", 0.0)
        conf      = f.get("confidence", 0)
        reason    = f.get("reason", "")

        diff_type = _classify_difference(field, stored, extracted, status, score)
        action    = _recommended_action(status, diff_type, score)

        result.append({
            "field":              field,
            "stored":             stored,
            "extracted":          extracted,
            "difference_type":    diff_type,
            "match_score":        score,
            "status":             status,
            "confidence":         conf,
            "reason":             reason,
            "recommended_action": action,
        })
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def decide_validation_status(
    doc_type:          str,
    ocr_confidence:    float,
    validation_result: Dict,
    extracted:         Dict,
) -> Dict:
    """
    Main decision function.

    Returns:
        {
            "decision":           str,   # AUTO_APPROVED | REVIEW_REQUIRED | AUTO_REJECTED
            "priority":           int,   # 1 | 2 | 3
            "reasons":            list,
            "auto_correctable":   bool,
            "comparison":         list,  # side-by-side field comparison
            "overall_status":     str,   # from validation_result
        }
    """
    rule_result: RuleResult = evaluate_rules(
        doc_type          = doc_type,
        ocr_confidence    = ocr_confidence,
        validation_result = validation_result,
        extracted         = extracted,
    )

    fields       = validation_result.get("fields", [])
    comparison   = build_comparison_payload(fields)
    overall      = validation_result.get("overall_status", "MISMATCH")

    decision_output = {
        "decision":         rule_result.decision,
        "priority":         rule_result.priority,
        "reasons":          rule_result.reasons,
        "auto_correctable": rule_result.auto_correctable,
        "comparison":       comparison,
        "overall_status":   overall,
        "ocr_confidence":   ocr_confidence,
    }

    logger.info(
        "[decision_engine] decision=%s priority=%d auto_correctable=%s overall=%s",
        rule_result.decision, rule_result.priority,
        rule_result.auto_correctable, overall,
    )

    return decision_output
