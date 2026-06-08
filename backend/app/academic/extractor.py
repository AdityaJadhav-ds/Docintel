"""
app/academic/extractor.py — Master academic extraction pipeline v3
==================================================================
New architecture:
  1. Load image
  2. Full-page OCR  (for classification + header fields)
  3. Zone layout engine (ZONE A/B/D targeted extraction)
  4. Merge: layout engine overrides full-page values
  5. Name cleanup
  6. Confidence scoring + structured response

ISOLATION: Never touches Aadhaar/PAN pipelines.
"""

from __future__ import annotations
import io, re, time, uuid
from typing import Dict, Any, Optional
from PIL import Image

from app.core.logger import logger
from app.academic.smart_extractor import smart_extract, _field_confidence
from app.academic.academic_document_layout_engine import extract_with_layout_engine


# ── Image loading ──────────────────────────────────────────────────────────────

def _load_image(file_input) -> Optional[Image.Image]:
    try:
        if isinstance(file_input, Image.Image):
            return file_input.convert("RGB")
        if isinstance(file_input, (bytes, bytearray)):
            if file_input[:4] == b"%PDF":
                from app.files.pdf_converter import pdf_first_page
                return pdf_first_page(file_input)
            return Image.open(io.BytesIO(file_input)).convert("RGB")
        if hasattr(file_input, "read"):
            data = file_input.read()
            if hasattr(file_input, "seek"):
                file_input.seek(0)
            return _load_image(data)
        if isinstance(file_input, str):
            if file_input.lower().endswith(".pdf"):
                from app.files.pdf_converter import pdf_first_page
                return pdf_first_page(file_input)
            return Image.open(file_input).convert("RGB")
    except Exception as exc:
        logger.error("[academic_extractor] Image load failed: %s", exc)
    return None


# ── Full-page OCR ──────────────────────────────────────────────────────────────

def _run_ocr(image: Image.Image) -> Dict[str, Any]:
    try:
        import numpy as np
        from app.ocr.preprocessor import preprocess_image
        from app.ocr.engine import run_ocr_on_variants
        arr      = np.array(image.convert("RGB"))
        variants = preprocess_image(arr)
        return run_ocr_on_variants(variants)
    except Exception as exc:
        logger.warning("[academic_extractor] Primary OCR failed (%s), Tesseract fallback", exc)
        try:
            # import pytesseract
            text = pytesseract.image_to_string(image, config="--oem 3 --psm 6", lang="eng")
            return {"merged_text": text.strip(), "avg_confidence": 0.55, "engines_used": ["tesseract_fallback"]}
        except Exception as exc2:
            logger.error("[academic_extractor] All OCR failed: %s", exc2)
            return {"merged_text": "", "avg_confidence": 0.0, "engines_used": []}


# ── Name cleanup ───────────────────────────────────────────────────────────────

_NAME_LEADING = re.compile(r"^[^A-Za-z\u0900-\u097F]+")
_NAME_SYMBOLS = re.compile(r"[{}\[\]|:;.,_\-+=~`<>@#$%^&*()\\\"\\'!?/]")

def _clean_name(name: str) -> str:
    if not name:
        return name
    original = name.strip()
    cleaned  = _NAME_SYMBOLS.sub(" ", original)
    cleaned  = _NAME_LEADING.sub("", cleaned)
    cleaned  = " ".join(cleaned.split())
    if not cleaned or not cleaned[0].isalpha() or len(cleaned.split()) < 2 or len(cleaned) < 4:
        fallback = _NAME_LEADING.sub("", original).strip()
        return fallback.title() if fallback else original
    return cleaned.title()


# ── Confidence ─────────────────────────────────────────────────────────────────

def _compute_confidence(extracted: Dict, ocr_conf: float) -> float:
    ext_conf   = _field_confidence(extracted)
    ocr_weight = min(ocr_conf, 1.0)
    return round(min(ext_conf * 0.65 + ocr_weight * 0.35, 1.0), 3)


# ── Main pipeline ──────────────────────────────────────────────────────────────

def analyze_academic_document(
    file_input,
    doc_type_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full pipeline: file → OCR → zone layout engine → merge → response.

    Args:
        file_input:    bytes | BytesIO | PIL Image | file path
        doc_type_hint: "ssc" | "hsc" | "degree" | None (auto-detect)

    Returns structured dict.
    """
    doc_id  = str(uuid.uuid4())
    t_start = time.time()

    # 1. Load image
    image = _load_image(file_input)
    if image is None:
        return {
            "status": "failed", "document_id": doc_id, "confidence": 0.0,
            "errors": ["Could not open or render the uploaded file. Check format/quality."],
            "warnings": [],
        }

    # 2. Full-page OCR (for classification + fallback fields)
    ocr_result = _run_ocr(image)
    raw_text   = ocr_result.get("merged_text", "")
    ocr_conf   = ocr_result.get("avg_confidence", 0.0)
    engines    = ocr_result.get("engines_used", [])

    logger.info("[academic_extractor] OCR: %d chars conf=%.2f engines=%s",
                len(raw_text), ocr_conf, engines)

    if len(raw_text.strip()) < 40:
        return {
            "status": "failed", "document_id": doc_id, "confidence": 0.0,
            "raw_text": raw_text,
            "errors": [f"OCR returned very little text ({len(raw_text.strip())} chars). Upload a clearer scan."],
        }

    # 3. Semantic classification (ONLY for document type)
    hint      = doc_type_hint if doc_type_hint in ("ssc", "hsc", "degree") else None
    smart_res = smart_extract(raw_text, doc_type_hint=hint)
    doc_type  = smart_res.get("document_type", "unknown")

    # Start fresh — DO NOT use full-page OCR for fields anymore
    extracted = {}

    # 4. Zone layout engine — runs for all academic types
    try:
        import numpy as np
        img_arr = np.array(image.convert("RGB"))
        layout  = extract_with_layout_engine(
            img_arr, doc_id=doc_id, doc_type=doc_type, full_text=raw_text
        )
        layout_ext = layout.get("extracted", {})

        # Merge ONLY from layout engine
        for field, value in layout_ext.items():
            extracted[field] = value
            logger.info("[academic_extractor] Layout ROI override: %s=%s", field, value)

    except Exception as exc:
        logger.warning("[academic_extractor] Layout engine failed (non-fatal): %s", exc)

    # Completely remove unwanted fields from response
    for field in ["total_marks", "obtained_marks", "grade", "student_name"]:
        extracted.pop(field, None)

    # 5. Name cleanup
    if extracted.get("candidate_name"):
        extracted["candidate_name"] = _clean_name(extracted["candidate_name"])

    # 6. Confidence + response
    confidence = _compute_confidence(extracted, ocr_conf)
    elapsed    = round(time.time() - t_start, 2)

    # Friendly doc_type label mapping
    _TYPE_LABEL = {
        "hsc":    "12th_hsc", "ssc": "10th_ssc",
        "degree": "degree",   "unknown": "unknown",
    }
    display_type = _TYPE_LABEL.get(doc_type, doc_type)

    detection = {
        "document_type": display_type,
        "confidence":    round(confidence * 100, 1),
        "reason":        f"Zone layout engine + semantic classification ({len(raw_text)} chars)",
    }
    status = "success" if confidence >= 0.25 else "partial"

    logger.info("[academic_extractor] Done: type=%s conf=%.3f elapsed=%ss",
                doc_type, confidence, elapsed)

    return {
        "status":      status,
        "document_id": doc_id,
        "doc_type":    doc_type,
        "detection":   detection,
        "extracted":   extracted,
        "raw_text":    raw_text,
        "confidence":  confidence,
        "warnings":    [],
        "ocr_engines": engines,
        "elapsed_s":   elapsed,
    }
