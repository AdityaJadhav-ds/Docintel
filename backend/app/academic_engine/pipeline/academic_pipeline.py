"""
academic_engine/pipeline/academic_pipeline.py
===============================================
Master Academic Intelligence Pipeline — Orchestrates all engine stages.

Pipeline flow:
  1. Load / rasterise input (image / PDF / bytes)
  2. Restore document (12-stage preprocessing)
  3. Classify document (type + subtype)
  4. Extract layout zones (A/B/C/D/E/F)
  5. ROI preprocessing (zone-specific strategies)
  6. Hybrid OCR per zone
  7. Field extraction from zone texts
  8. Validation
  9. Confidence scoring
  10. Debug artefact saving
  11. Return structured response

Output schema:
  {
    "document_category": str,
    "document_type":     str,
    "candidate_name":    str | null,   # extracted by universal name extractor
    "name_confidence":   float,        # 0.0–1.0 confidence for the name
    "passing_year":      str | null,
    "percentage":        str | null,
    "cgpa":              str | null,
    "grade_class":       str | null,
    "_meta": {
      "document_id":  str,
      "confidence":   {...},
      "elapsed_s":    float,
      "ocr_engines":  list,
      "status":       str,
      "warnings":     list,
    }
  }

Performance target: < 5 seconds for typical marksheet images.
Supports async processing via run_pipeline_async().

ISOLATION: Completely separate from KYC / Aadhaar / PAN extraction.
"""

from __future__ import annotations
import io
import time
import uuid
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL IMPORTS (engine sub-modules)
# ─────────────────────────────────────────────────────────────────────────────

from app.academic_engine.universal.universal_document_classifier import classify_document_universally
from app.academic_engine.preprocessing.document_restoration import (
    restore_document,
    preprocess_for_zone,
)
from app.academic_engine.layout_engine.academic_layout_engine import extract_zones
from app.academic_engine.ocr.hybrid_ocr import (
    ocr_image, ocr_roi_block, ocr_roi_percentage, ocr_pdf,
)
from app.academic_engine.extractors.field_extractors import extract_all_fields
from app.academic_engine.validators.academic_validators import validate_extracted_fields
from app.academic_engine.confidence.confidence_engine import compute_overall_confidence
from app.academic_engine.debug.academic_debug import create_debug_session

from app.academic_engine.universal.universal_restoration import normalize_document
from app.academic_engine.spatial_v3.spatial_intelligence import build_spatial_graph, extract_spatial_fields

# ── Layout Intelligence v2 (DEPRECATED, using v3) ──────────────────────
_LAYOUT_V2_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def _load_image(file_input: Any) -> Optional[np.ndarray]:
    """
    Load any file input as a BGR numpy array.
    Supports: bytes, BytesIO, file path (str), PIL Image, ndarray.
    PDFs are rasterised (first page).
    """
    import cv2

    try:
        # Already a numpy array
        if isinstance(file_input, np.ndarray):
            if len(file_input.shape) == 2:
                return cv2.cvtColor(file_input, cv2.COLOR_GRAY2BGR)
            return file_input

        # PIL Image
        try:
            from PIL import Image as PILImage
            if isinstance(file_input, PILImage.Image):
                arr = np.array(file_input.convert("RGB"))
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except ImportError:
            pass

        # Bytes / BytesIO
        if isinstance(file_input, (bytes, bytearray, memoryview)):
            data = bytes(file_input)
        elif hasattr(file_input, "read"):
            data = file_input.read()
        elif isinstance(file_input, str):
            # File path
            if file_input.lower().endswith(".pdf"):
                data = open(file_input, "rb").read()
            else:
                img = cv2.imread(file_input)
                return img
        else:
            logger.error("[pipeline] Unknown file_input type: %s", type(file_input))
            return None

        # PDF bytes → rasterise
        if data[:4] == b"%PDF":
            return _rasterise_pdf(data)

        # Image bytes → decode
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            # Try PIL fallback
            try:
                from PIL import Image as PILImage
                pil = PILImage.open(io.BytesIO(data)).convert("RGB")
                arr = np.array(pil)
                img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            except Exception:
                pass
        return img

    except Exception as exc:
        logger.error("[pipeline] Image load error: %s", exc)
        return None


def _rasterise_pdf(pdf_bytes: bytes) -> Optional[np.ndarray]:
    """Rasterise first page of a PDF to BGR numpy array at 200 DPI."""
    # Try pypdfium2 first (high quality)
    try:
        import pypdfium2 as pdfium
        import cv2
        doc  = pdfium.PdfDocument(pdf_bytes)
        page = doc[0]
        bm   = page.render(scale=200 / 72, rotate=0)
        pil  = bm.to_pil()
        arr  = np.array(pil.convert("RGB"))
        doc.close()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        pass

    # Fallback: PyMuPDF
    try:
        import fitz, cv2
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        mat  = fitz.Matrix(200 / 72, 200 / 72)
        pix  = page.get_pixmap(matrix=mat)
        arr  = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        doc.close()
        if pix.n == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        elif pix.n == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return arr
    except Exception:
        pass

    # Final fallback: pdf2image
    try:
        from pdf2image import convert_from_bytes
        import cv2
        pages = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1)
        if pages:
            arr = np.array(pages[0].convert("RGB"))
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        pass

    logger.error("[pipeline] All PDF rasterisation methods failed")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# ZONE OCR STRATEGY
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_zone(zone_name: str, roi: Optional[np.ndarray]) -> str:
    """Run OCR on a single zone ROI with zone-specific strategy."""
    if roi is None or roi.size == 0:
        return ""
    try:
        # Zone-specific OCR strategies
        if zone_name == "percentage":
            result = ocr_roi_percentage(roi)
        elif zone_name in ("header", "cert_stmt"):
            result = ocr_roi_block(roi)
        else:
            result = ocr_image(roi, use_easyocr=True)
        return result.get("text", "") or ""
    except Exception as exc:
        logger.warning("[pipeline] OCR failed for zone '%s': %s", zone_name, exc)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    file_input: Any,
    hint: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute the full academic document intelligence pipeline.

    Args:
        file_input: bytes | BytesIO | PIL Image | ndarray | file path
        hint:       Optional type hint: 'ssc' | 'hsc' | 'degree' | 'auto' | None
        doc_id:     Optional document ID (auto-generated if None)

    Returns:
        Structured extraction result dict.
    """
    doc_id  = doc_id or str(uuid.uuid4())
    t_start = time.monotonic()
    debug   = create_debug_session(doc_id)
    warnings: List[str] = []

    # ── STEP 1: Try PDF digital text extraction first ─────────────────────────
    pdf_bytes = None
    if isinstance(file_input, (bytes, bytearray, memoryview)):
        data = bytes(file_input)
        if data[:4] == b"%PDF":
            pdf_bytes = data

    full_text_from_pdf = ""
    pdf_ocr_engines = []
    if pdf_bytes:
        pdf_result = ocr_pdf(pdf_bytes)
        if not pdf_result.get("needs_rasterise") and len(pdf_result.get("text", "")) > 100:
            full_text_from_pdf = pdf_result["text"]
            pdf_ocr_engines    = [pdf_result.get("engine", "pdf")]
            logger.info("[pipeline] PDF digital text extracted: %d chars", len(full_text_from_pdf))

    # ── STEP 2: Load / rasterise image ────────────────────────────────────────
    t_img = time.monotonic()
    img = _load_image(file_input)
    if img is None:
        logger.error("[pipeline-validation] 2. image read: FAIL | elapsed: %.2fs", time.monotonic() - t_img)
        return _error_response(doc_id, "Could not open or render the uploaded file.", t_start)
    logger.info("[pipeline-validation] 2. image read: PASS | elapsed: %.2fs | summary: %s", time.monotonic() - t_img, img.shape)

    original_img = img.copy()
    debug.save_image("01_original", original_img)

    # ── STEP 3: Universal Document Restoration ───────────────────────────────
    t_rest = time.monotonic()
    normalized = normalize_document(img)
    restored_img = normalized["clean_scan"]
    debug.save_image("02_restored", restored_img)
    logger.info("[pipeline-validation] 3. scanner restore: PASS | elapsed: %.2fs", time.monotonic() - t_rest)

    # ── STEP 4: Quick classification OCR ─────────────────────────────────────
    classification_text = ""
    classification_ocr_conf = 0.0

    if full_text_from_pdf:
        classification_text     = full_text_from_pdf
        classification_ocr_conf = 0.95
        logger.info("[pipeline] STEP4 classification via PDF text (%d chars)", len(classification_text))
    else:
        t4 = time.monotonic()
        try:
            fp_restored = ocr_image(restored_img, use_easyocr=False)
            classification_text = fp_restored.get("text", "").strip()
            classification_ocr_conf = fp_restored.get("confidence", 0.4)
            ocr_engines_used = [fp_restored.get("engine", "tesseract")]
        except Exception as e:
            logger.warning("[pipeline] STEP4 restored OCR failed: %s", e)

    hint_clean = hint.strip().lower() if hint and hint != "auto" else None
    classification  = classify_document_universally(classification_text)
    doc_category    = classification["document_category"]
    doc_subtype     = classification["subtype"]

    logger.info("[pipeline] document classifier output: category=%s subtype=%s conf=%.2f", doc_category, doc_subtype, classification.get("subtype_confidence", 0.0))
    logger.info("[pipeline-validation] 5. OCR & Classification: PASS | elapsed: %.2fs | summary: %s (%s)", time.monotonic() - t4 if 't4' in locals() else 0, doc_category, doc_subtype)

    # ── STEP 5: UNIVERSAL SEMANTIC PARSER ─────────────────────────────────────
    from app.academic_engine.universal_parser import run_universal_parser
    t_parser = time.monotonic()
    
    raw_extracted = run_universal_parser(restored_img)
    universal_raw_text = raw_extracted.pop("raw_text", "")
    parser_reasoning = raw_extracted.pop("_parser_reasoning", {})
    
    logger.info("[pipeline-validation] 6. Universal Semantic Parser: PASS | elapsed: %.2fs", time.monotonic() - t_parser)
    logger.info("[pipeline] Raw extracted: %s", {k: v for k, v in raw_extracted.items() if v})

    # ── STEP 8: Validation ─────────────────────────────────────────────────────
    t_val = time.monotonic()
    validated = validate_extracted_fields(raw_extracted)
    validation_warnings = validated.pop("_validation_warnings", [])
    warnings.extend(validation_warnings)
    logger.info("[pipeline-validation] 10. field validation: PASS | elapsed: %.2fs | warnings: %d", time.monotonic() - t_val, len(validation_warnings))
    logger.info("[pipeline] Validated: %s", {k: v for k, v in validated.items() if v})

    # Combine texts early — needed by name extractor and final output
    combined_raw_text = classification_text + "\n" + universal_raw_text
    logger.info("[pipeline] OCR raw text length: %d chars", len(combined_raw_text))

    # ── STEP 8b: Universal Name Extraction ───────────────────────────────────
    candidate_name: Optional[str] = None
    name_confidence: float = 0.0
    try:
        from app.academic_engine.extractors.academic_name_extractor import extract_academic_name
        doc_subtype = classification.get("subtype", "marksheet") or "marksheet"
        name_result = extract_academic_name(
            ocr_text=combined_raw_text,
            zone_texts={"candidate": combined_raw_text},
            doc_subtype=doc_subtype,
        )
        candidate_name  = name_result.name
        name_confidence = name_result.confidence
        logger.info(
            "[pipeline] Name extraction: name='%s' conf=%.3f method=%s",
            candidate_name, name_confidence, name_result.method,
        )
        if name_result.debug.get("candidates"):
            logger.debug("[pipeline] Name candidates: %s", name_result.debug["candidates"][:5])
    except Exception as _ne:
        logger.warning("[pipeline] Name extraction failed: %s", _ne)

    # ── STEP 9: Confidence scoring ─────────────────────────────────────────────
    avg_ocr_conf = classification_ocr_conf
    confidence = compute_overall_confidence(validated, ocr_confidence=avg_ocr_conf)

    # ── STEP 10: Build final response ──────────────────────────────────────────
    elapsed = round(time.monotonic() - t_start, 2)
    ocr_engines_used = getattr(locals(), 'ocr_engines_used', ["tesseract", "universal_parser"])
    engines_dedup = list(dict.fromkeys(ocr_engines_used))

    status = "success" if confidence["grade"] in ("high", "medium") else "partial"
    if confidence["fields_found"] == 0:
        status = "failed"

    # combined_raw_text already built above
    logger.debug("[pipeline] Building final output")
    
    final_output = {
        "document_category": classification["document_category"],
        "document_type":     classification.get("document_type", "unknown"),
        "candidate_name":    candidate_name,
        "name_confidence":   round(name_confidence, 3),
        "passing_year":      validated.get("passing_year"),
        "percentage":        validated.get("percentage"),
        "cgpa":              validated.get("cgpa"),
        "grade_class":       validated.get("grade_class"),
        "raw_text":          combined_raw_text,
        "_meta": {
            "document_id":           doc_id,
            "status":                status,
            "confidence":            confidence,
            "elapsed_s":             elapsed,
            "ocr_engines":           engines_dedup,
            "warnings":              warnings,
            "level":                 classification.get("level"),
            "subtype":               classification.get("subtype"),
            "level_confidence":      classification.get("level_confidence"),
            "subtype_confidence":    classification.get("subtype_confidence"),
            "extraction_engine":     "universal_parser",
            "layout_v2_meta":        parser_reasoning,
        },
    }

    debug.finalize(
        original=original_img,
        restored=restored_img,
        zones={},
        preprocessed={},
        zone_texts={"raw": combined_raw_text},
        extracted=raw_extracted,
        confidence=confidence,
        final_output=final_output,
    )

    logger.info(
        "[pipeline] DONE: doc_id=%s engine=%s status=%s conf=%.3f elapsed=%.1fs",
        doc_id,
        final_output["_meta"]["extraction_engine"],
        status, confidence["overall"], elapsed,
    )
    
    logger.info("[pipeline-validation] 11. frontend response generation: PASS | elapsed: %.2fs", elapsed)

    return final_output


def _error_response(doc_id: str, message: str, t_start: float) -> Dict[str, Any]:
    elapsed = round(time.monotonic() - t_start, 2)
    return {
        "document_category": "unknown",
        "document_type":     "Unknown Document",
        "candidate_name":    None,
        "name_confidence":   0.0,
        "passing_year":      None,
        "percentage":        None,
        "cgpa":              None,
        "grade_class":       None,
        "raw_text":          "",
        "_meta": {
            "document_id": doc_id,
            "status":      "failed",
            "confidence":  {"overall": 0.0, "grade": "insufficient"},
            "elapsed_s":   elapsed,
            "ocr_engines": [],
            "warnings":    [],
            "errors":      [message],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ASYNC WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="academic_engine")


async def run_pipeline_async(
    file_input: Any,
    hint: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async wrapper for the synchronous pipeline.
    Runs in a thread pool to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor,
        lambda: run_pipeline(file_input, hint=hint, doc_id=doc_id),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BULK PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

async def run_pipeline_bulk(
    file_inputs: List[Any],
    hints: Optional[List[Optional[str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Process multiple documents concurrently.

    Args:
        file_inputs: List of file inputs (bytes / paths / PIL Images).
        hints:       Optional list of type hints (same length as file_inputs).

    Returns:
        List of result dicts in same order as input.
    """
    if hints is None:
        hints = [None] * len(file_inputs)

    tasks = [
        run_pipeline_async(fi, hint=h)
        for fi, h in zip(file_inputs, hints)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    return list(results)
