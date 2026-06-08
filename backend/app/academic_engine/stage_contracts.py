"""
stage_contracts.py
==================
Strict output schemas for each pipeline stage.
Every stage MUST validate its return against these contracts.
No stage may return arbitrary keys outside the schema.
"""

from typing import Optional


# ──────────────────────────────────────────────
# VISION CONTRACT
# Input:  np.ndarray (image)
# Output: VisionOutput
# Responsibility: ONLY improve image quality.
# ──────────────────────────────────────────────
def make_vision_output(
    success: bool,
    cleaned_image=None,  # np.ndarray | None
    zones: Optional[dict] = None,
    metrics: Optional[dict] = None,
    errors: Optional[list] = None,
) -> dict:
    return {
        "success": success,
        "cleaned_image": cleaned_image,
        "zones": zones or {},
        "metrics": metrics or {},
        "errors": errors or [],
    }


# ──────────────────────────────────────────────
# OCR CONTRACT
# Input:  np.ndarray + zones dict
# Output: OcrOutput
# Responsibility: ONLY read text from image.
# ──────────────────────────────────────────────
def make_ocr_output(
    success: bool,
    words: Optional[list] = None,
    merged_text: str = "",
    confidence: float = 0.0,
    errors: Optional[list] = None,
) -> dict:
    return {
        "success": success,
        "words": words or [],
        "merged_text": merged_text,
        "confidence": confidence,
        "errors": errors or [],
    }


# ──────────────────────────────────────────────
# SEMANTIC CONTRACT
# Input:  word list (from OCR)
# Output: SemanticOutput
# Responsibility: ONLY find field candidates.
# ──────────────────────────────────────────────
def make_semantic_output(
    success: bool,
    candidates: Optional[dict] = None,
    extracted_fields: Optional[dict] = None,
    rejected_fields: Optional[dict] = None,
    errors: Optional[list] = None,
) -> dict:
    return {
        "success": success,
        "candidates": candidates or {},
        "extracted_fields": extracted_fields or {},
        "rejected_fields": rejected_fields or {},
        "errors": errors or [],
    }


# ──────────────────────────────────────────────
# VALIDATION CONTRACT
# Input:  extracted_fields dict
# Output: ValidationOutput
# Responsibility: ONLY approve or reject values.
# ──────────────────────────────────────────────
def make_validation_output(
    success: bool,
    valid_fields: Optional[dict] = None,
    invalid_fields: Optional[dict] = None,
    warnings: Optional[list] = None,
    errors: Optional[list] = None,
) -> dict:
    return {
        "success": success,
        "valid_fields": valid_fields or {},
        "invalid_fields": invalid_fields or {},
        "warnings": warnings or [],
        "errors": errors or [],
    }
