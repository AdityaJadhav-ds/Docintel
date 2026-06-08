"""
app/review/approval_rules.py — Enterprise approval rule definitions
====================================================================
Single source of truth for all thresholds and rule logic.
Rules are pure functions — no DB calls, no side effects.

DECISION OUTCOMES:
  AUTO_APPROVED    — high confidence, no mismatches
  REVIEW_REQUIRED  — uncertain, needs human eyes
  AUTO_REJECTED    — definite mismatch or bad document
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Optional


# ── Threshold constants ───────────────────────────────────────────────────────

class Thresholds:
    # OCR confidence (0-1 scale, from parser)
    OCR_HIGH    = 0.85      # >= this → strong signal
    OCR_MEDIUM  = 0.40      # >= this → uncertain
    # OCR below MEDIUM → AUTO_REJECTED (can't trust extraction)

    # Name fuzzy match score (0-100)
    NAME_AUTO_APPROVE = 95   # >= this → approve name
    NAME_REVIEW       = 75   # >= this → needs review
    # Name below REVIEW → MISMATCH → reject

    # Field-level confidence (0-100)
    FIELD_HIGH   = 80
    FIELD_MEDIUM = 50


# ── Priority scoring ──────────────────────────────────────────────────────────

class Priority:
    HIGH   = 1   # urgent — ID mismatch, multiple failures
    MEDIUM = 2   # normal — name variation, low OCR
    LOW    = 3   # minor — small typo only


@dataclass
class RuleResult:
    decision:  str               # AUTO_APPROVED | REVIEW_REQUIRED | AUTO_REJECTED
    priority:  int               # 1 | 2 | 3
    reasons:   List[str]         # human-readable rule reasons
    auto_correctable: bool = False   # can system auto-fix?


# ── Rule helpers ──────────────────────────────────────────────────────────────

def _field_statuses(fields: List[Dict]) -> Dict[str, str]:
    """Map field name → status from validation result fields list."""
    return {f["field"]: f.get("status", "MISMATCH") for f in fields}


def _field_scores(fields: List[Dict]) -> Dict[str, float]:
    return {f["field"]: f.get("match_score", 0) for f in fields}


def _missing_fields(doc_type: str, extracted: Dict) -> List[str]:
    """Return list of fields that are None in the extracted data."""
    required = ["name", "dob"]
    if doc_type == "aadhaar":
        required.append("aadhaar_number")
    elif doc_type == "pan":
        required.append("pan_number")
    return [f for f in required if not extracted.get(f)]


# ── Main rule evaluator ───────────────────────────────────────────────────────

def evaluate_rules(
    doc_type:          str,
    ocr_confidence:    float,
    validation_result: Dict,
    extracted:         Dict,
) -> RuleResult:
    """
    Apply all approval rules and return a final RuleResult.

    Args:
        doc_type:          'aadhaar' | 'pan' | 'unknown'
        ocr_confidence:    0.0 – 1.0 from OCR pipeline
        validation_result: output of build_validation_result()
        extracted:         output of aadhaar_parser / pan_parser

    Returns:
        RuleResult(decision, priority, reasons, auto_correctable)
    """
    reasons:   List[str] = []
    rejections: List[str] = []
    reviews:    List[str] = []
    priority = Priority.LOW

    # ── Rule R0: Unknown document type ────────────────────────────────────────
    if doc_type == "unknown":
        return RuleResult(
            decision  = "AUTO_REJECTED",
            priority  = Priority.HIGH,
            reasons   = ["Document type could not be detected."],
        )

    # ── Rule R1: OCR confidence gate ─────────────────────────────────────────
    if ocr_confidence < Thresholds.OCR_MEDIUM:
        rejections.append(
            f"OCR confidence {ocr_confidence:.0%} is below minimum threshold "
            f"({Thresholds.OCR_MEDIUM:.0%}). Document likely unreadable."
        )
        priority = Priority.HIGH

    # ── Rule R2: Missing fields ───────────────────────────────────────────────
    missing = _missing_fields(doc_type, extracted)
    if len(missing) >= 2:
        rejections.append(f"Multiple fields could not be extracted: {', '.join(missing)}.")
        priority = Priority.HIGH
    elif len(missing) == 1:
        reviews.append(f"Field '{missing[0]}' could not be extracted — needs verification.")
        priority = max(priority, Priority.MEDIUM)  # don't downgrade HIGH

    # ── Rule R3: Overall validation status ────────────────────────────────────
    overall = validation_result.get("overall_status", "MISMATCH")
    fields  = validation_result.get("fields", [])
    statuses = _field_statuses(fields)
    scores   = _field_scores(fields)

    if overall == "OCR_FAILED":
        rejections.append("OCR extraction produced no usable data.")
        priority = Priority.HIGH

    # ── Rule R4: ID number matching ───────────────────────────────────────────
    id_field = "aadhaar_number" if doc_type == "aadhaar" else "pan_number"
    id_status = statuses.get(id_field, "MISMATCH")
    if id_status == "MISMATCH":
        rejections.append(
            f"{id_field.replace('_', ' ').title()} does not match stored value. "
            "This is a critical mismatch."
        )
        priority = Priority.HIGH
    elif id_status == "POSSIBLE_MATCH":
        reviews.append(f"{id_field.replace('_', ' ').title()} has possible OCR confusion — verify manually.")
        priority = max(priority, Priority.MEDIUM)
    else:
        reasons.append(f"{id_field.replace('_', ' ').title()} matched exactly. ✓")

    # ── Rule R5: Name matching ────────────────────────────────────────────────
    name_status = statuses.get("name", "MISMATCH")
    name_score  = scores.get("name", 0)

    if name_status == "MISMATCH":
        rejections.append(
            f"Name mismatch detected (score={name_score:.0f}/100). "
            "Extracted name does not match stored data."
        )
        priority = max(priority, Priority.HIGH)
    elif name_status == "POSSIBLE_MATCH":
        reviews.append(
            f"Name has minor variation (score={name_score:.0f}/100). "
            "May be OCR typo — review recommended."
        )
        priority = max(priority, Priority.MEDIUM)
    elif name_score < Thresholds.NAME_AUTO_APPROVE:
        reviews.append(
            f"Name score {name_score:.0f}/100 is below auto-approve threshold "
            f"({Thresholds.NAME_AUTO_APPROVE}). Manual confirmation needed."
        )
        priority = max(priority, Priority.MEDIUM)
    else:
        reasons.append(f"Name matched with score {name_score:.0f}/100. ✓")

    # ── Rule R6: DOB matching ─────────────────────────────────────────────────
    dob_status = statuses.get("dob", "MISMATCH")
    if dob_status == "MISMATCH":
        rejections.append("Date of Birth does not match stored value.")
        priority = max(priority, Priority.HIGH)
    elif dob_status == "POSSIBLE_MATCH":
        reviews.append("Date of Birth: only year could be verified — full date check needed.")
        priority = max(priority, Priority.MEDIUM)
    else:
        reasons.append("Date of Birth matched. ✓")

    # ── Rule R7: OCR confidence quality check ─────────────────────────────────
    if Thresholds.OCR_MEDIUM <= ocr_confidence < Thresholds.OCR_HIGH:
        reviews.append(
            f"OCR confidence {ocr_confidence:.0%} is acceptable but not high — "
            "result may have minor extraction errors."
        )
        priority = max(priority, Priority.MEDIUM)
    elif ocr_confidence >= Thresholds.OCR_HIGH:
        reasons.append(f"OCR confidence {ocr_confidence:.0%} is high. ✓")

    # ── Final decision ────────────────────────────────────────────────────────
    all_reasons = reasons + reviews + rejections

    if rejections:
        decision = "AUTO_REJECTED"
    elif reviews:
        decision = "REVIEW_REQUIRED"
        # Special case: OCR confidence is good + only minor name variation → auto-correctable
        auto_correctable = (
            not rejections
            and ocr_confidence >= Thresholds.OCR_HIGH
            and name_status == "POSSIBLE_MATCH"
            and name_score >= 88
            and id_status == "MATCH"
            and dob_status == "MATCH"
        )
        return RuleResult(
            decision         = decision,
            priority         = priority,
            reasons          = all_reasons,
            auto_correctable = auto_correctable,
        )
    else:
        decision = "AUTO_APPROVED"
        priority = Priority.LOW

    return RuleResult(
        decision  = decision,
        priority  = priority,
        reasons   = all_reasons,
    )
