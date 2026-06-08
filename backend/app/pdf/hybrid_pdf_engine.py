"""
app/pdf/hybrid_pdf_engine.py — Hybrid PDF processing engine
============================================================
THE CORRECT ENTERPRISE PDF STRATEGY:

  1. Try direct text extraction (digital PDFs, WhatsApp PDFs, e-signed docs)
  2. If text quality is good → parse directly (NO OCR)
  3. If text is junk/empty → fall back to page rendering + OCR

This eliminates all "garbage OCR text" from digital PDFs because we never
run OCR on text that's already selectable.

Flow:
  PDF bytes
    │
    ├─ extract_pdf_text() ─── try pypdfium2 / pdfplumber / pdfminer
    │
    ├─ classify_pdf() ──────── DIGITAL / SCANNED / HYBRID
    │
    ├─ DIGITAL → parse directly ──────────────────────── return result
    │
    └─ SCANNED/LOW QUALITY → pdf_to_pages() + OCR ────── return result

Result:
  HybridPdfResult with extraction_source = "direct_pdf_text" | "ocr_fallback"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.logger import logger
from app.pdf.text_extractor import extract_pdf_text, merge_page_texts, PageText
from app.pdf.scanned_detector import classify_pdf, PdfClassification, PdfType


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class HybridPdfResult:
    # Core extraction output (same shape as ocr_pipeline.process_document)
    doc_type: str = "unknown"
    extracted: Dict = field(default_factory=dict)
    raw_text: str = ""
    ocr_confidence: float = 0.0

    # Source metadata
    extraction_source: str = ""     # "direct_pdf_text" | "ocr_fallback" | "hybrid"
    pdf_type: str = ""              # "digital" | "scanned" | "hybrid"
    page_count: int = 0
    digital_pages: int = 0
    text_quality: float = 0.0
    elapsed_sec: float = 0.0

    # Error state
    success: bool = True
    error: Optional[str] = None

    # Debug
    engines_used: List[str] = field(default_factory=list)
    pages_debug: List[Dict] = field(default_factory=list)


# ── Direct text → parser pipeline ────────────────────────────────────────────

def _parse_direct_text(merged_text: str, doc_type_hint: Optional[str]) -> Dict:
    """Run parsers on directly-extracted PDF text."""
    from app.ocr.detector import detect_document_type
    from app.parsers.aadhaar.engine import parse_aadhaar_v4
    from app.parsers.pan_parser import parse_pan

    doc_type = (
        doc_type_hint
        if doc_type_hint in ("aadhaar", "pan")
        else detect_document_type(merged_text)
    )
    logger.info("[hybrid_pdf] Direct parse: doc_type=%s text_len=%d", doc_type, len(merged_text))

    try:
        if doc_type == "aadhaar":
            extracted = parse_aadhaar_v4(merged_text)
        elif doc_type == "pan":
            extracted = parse_pan(merged_text)
        else:
            logger.warning("[hybrid_pdf] Unknown doc type — cannot parse")
            extracted = {}
    except Exception as exc:
        logger.error("[hybrid_pdf] Parser failed: %s", exc)
        extracted = {}

    # Confidence: how many of the 3 key fields were found
    if doc_type == "aadhaar":
        id_key = "aadhaar_number"
    elif doc_type == "pan":
        id_key = "pan_number"
    else:
        id_key = None

    found = sum(1 for k in ["name", id_key, "dob"] if k and extracted.get(k))
    confidence = round(found / 3.0, 4)
    extracted.setdefault("confidence", confidence)

    return {"doc_type": doc_type, "extracted": extracted, "confidence": confidence}


# ── OCR fallback pipeline ─────────────────────────────────────────────────────

def _run_ocr_on_pages(pdf_bytes: bytes, doc_type_hint: Optional[str]) -> Dict:
    """Render PDF pages and run the full OCR pipeline on each."""
    from app.files.pdf_converter import pdf_to_pages
    from app.services.ocr_pipeline import _run_full_pipeline, _merge_page_results, safe_has_array

    try:
        raw_pages = pdf_to_pages(pdf_bytes)
    except Exception as exc:
        return {"error": f"PDF rendering failed: {exc}", "doc_type": "unknown",
                "extracted": {}, "confidence": 0.0, "pages_debug": []}

    if not raw_pages:
        return {"error": "PDF rendered 0 pages", "doc_type": "unknown",
                "extracted": {}, "confidence": 0.0, "pages_debug": []}

    import cv2
    import numpy as np

    page_results = []
    for rp in raw_pages:
        if rp.is_blank:
            logger.debug("[hybrid_pdf] Skipping blank page %d", rp.page_num)
            continue
        try:
            arr = cv2.cvtColor(np.array(rp.image), cv2.COLOR_RGB2BGR)
            if not safe_has_array(arr):
                continue
            pr = _run_full_pipeline(arr, doc_type_hint)
            pr["page_num"] = rp.page_num
            page_results.append(pr)
            logger.info("[hybrid_pdf] OCR page %d: confidence=%.3f doc_type=%s",
                        rp.page_num, pr.get("ocr_confidence", 0), pr.get("doc_type", "?"))
        except Exception as exc:
            logger.warning("[hybrid_pdf] OCR page %d failed: %s", rp.page_num, exc)

    if not page_results:
        return {"error": "OCR failed on all pages", "doc_type": "unknown",
                "extracted": {}, "confidence": 0.0, "pages_debug": []}

    # Best page by confidence + field count
    def _score(pr):
        c = pr.get("ocr_confidence", 0.0)
        e = pr.get("extracted", {})
        n = sum(1 for v in [e.get("name"), e.get("dob"),
                             e.get("pan_number"), e.get("aadhaar_number")] if v)
        return c + n * 0.1

    page_results.sort(key=_score, reverse=True)
    best = page_results[0]
    doc_type = best.get("doc_type", "unknown")

    # Multi-page merge
    if len(page_results) > 1:
        extracted = _merge_page_results(page_results, doc_type)
        confidence = max(pr.get("ocr_confidence", 0) for pr in page_results)
    else:
        extracted  = best.get("extracted", {})
        confidence = best.get("ocr_confidence", 0.0)

    pages_debug = [{"page": pr["page_num"], "confidence": pr.get("ocr_confidence", 0)}
                   for pr in page_results]

    return {
        "doc_type":    doc_type,
        "extracted":   extracted,
        "raw_text":    best.get("raw_text", ""),
        "confidence":  confidence,
        "engines_used": best.get("engines_used", []),
        "pages_debug": pages_debug,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def process_pdf(
    pdf_bytes: bytes,
    doc_type_hint: Optional[str] = None,
) -> HybridPdfResult:
    """
    Hybrid PDF processing: direct extraction → OCR fallback.

    Args:
        pdf_bytes     : raw PDF bytes
        doc_type_hint : 'aadhaar' | 'pan' | None

    Returns:
        HybridPdfResult with extraction_source indicating which path was used.
    """
    t0 = time.monotonic()
    logger.info("[hybrid_pdf] Starting hybrid PDF engine (hint=%s, size=%d)",
                doc_type_hint, len(pdf_bytes))

    # ── Step 1: Extract embedded text ────────────────────────────────────────
    page_texts = extract_pdf_text(pdf_bytes)
    classification = classify_pdf(page_texts)

    logger.info("[hybrid_pdf] PDF classified: type=%s digital=%d/%d quality=%.2f",
                classification.pdf_type, classification.digital_pages,
                classification.total_pages, classification.overall_quality)

    pages_debug_base = [
        {
            "page": pt.page_num,
            "text_chars": pt.char_count,
            "quality": pt.quality_score,
            "is_digital": pt.is_digital,
            "engine": pt.engine,
        }
        for pt in page_texts
    ]

    # ── Step 2: Digital PDF → parse directly (no OCR) ────────────────────────
    if classification.use_direct_extraction:
        merged_text = merge_page_texts(page_texts)
        parse_result = _parse_direct_text(merged_text, doc_type_hint)

        doc_type   = parse_result["doc_type"]
        extracted  = parse_result["extracted"]
        confidence = parse_result["confidence"]

        # If direct extraction found the document type + at least one field → done!
        if doc_type != "unknown" and confidence > 0:
            elapsed = round(time.monotonic() - t0, 2)
            logger.info(
                "[hybrid_pdf] ✓ DIRECT PDF TEXT extraction succeeded: "
                "doc_type=%s confidence=%.3f elapsed=%.1fs",
                doc_type, confidence, elapsed
            )
            return HybridPdfResult(
                doc_type=doc_type,
                extracted=extracted,
                raw_text=merged_text,
                ocr_confidence=confidence,
                extraction_source="direct_pdf_text",
                pdf_type=classification.pdf_type.value,
                page_count=classification.total_pages,
                digital_pages=classification.digital_pages,
                text_quality=classification.overall_quality,
                elapsed_sec=elapsed,
                engines_used=[page_texts[0].engine if page_texts else "unknown"],
                pages_debug=pages_debug_base,
                success=True,
            )

        # Direct extraction produced doc_type=unknown or confidence=0 → try OCR
        logger.warning(
            "[hybrid_pdf] Direct text failed (doc_type=%s conf=%.2f) — falling back to OCR",
            doc_type, confidence
        )

    # ── Step 3: Scanned / low-quality → OCR pipeline ─────────────────────────
    logger.info("[hybrid_pdf] Using OCR fallback (PDF type=%s)", classification.pdf_type.value)
    ocr_result = _run_ocr_on_pages(pdf_bytes, doc_type_hint)

    if ocr_result.get("error"):
        elapsed = round(time.monotonic() - t0, 2)
        return HybridPdfResult(
            success=False,
            error=ocr_result["error"],
            pdf_type=classification.pdf_type.value,
            elapsed_sec=elapsed,
        )

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "[hybrid_pdf] ✓ OCR fallback completed: doc_type=%s confidence=%.3f elapsed=%.1fs",
        ocr_result.get("doc_type", "?"), ocr_result.get("confidence", 0), elapsed
    )

    return HybridPdfResult(
        doc_type=ocr_result.get("doc_type", "unknown"),
        extracted=ocr_result.get("extracted", {}),
        raw_text=ocr_result.get("raw_text", ""),
        ocr_confidence=ocr_result.get("confidence", 0.0),
        extraction_source="ocr_fallback",
        pdf_type=classification.pdf_type.value,
        page_count=classification.total_pages or len(ocr_result.get("pages_debug", [])),
        digital_pages=classification.digital_pages,
        text_quality=classification.overall_quality,
        elapsed_sec=elapsed,
        engines_used=ocr_result.get("engines_used", []),
        pages_debug=pages_debug_base + ocr_result.get("pages_debug", []),
        success=True,
    )
