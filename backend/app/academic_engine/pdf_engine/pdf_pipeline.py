"""
pdf_engine/pdf_pipeline.py
===========================
OPTIMIZED PDF Pipeline — FAST MODE.

Architecture:

  PDF bytes
    │
    ├─ pdf_renderer.render_pdf_pages()         → 250 DPI numpy images
    ├─ pdf_page_splitter.split_pages()         → ordered, filtered pages
    ├─ pdf_quality_optimizer.optimize_page()   → light normalisation only
    │
    └─ For EACH page (sequential, free memory after each):
         └─ pdf_light_pipeline.run_light_pipeline()
              ├─ Light preprocess  (no glare/shadow/super-res)
              ├─ PaddleOCR ONLY   (2 variants — grayscale + sharpened)
              ├─ SemanticParser   (reused, untouched)
              └─ Light validation (no retry loops)
    │
    └─ multi_page_merger.merge_page_results() → single unified result

Target: 5–15 seconds per page.
Image pipeline (MasterPipeline) is NOT used for PDFs.
PDFs are already clean — mobile-image recovery logic is NOT needed.
"""
from __future__ import annotations

import gc
import time
import uuid
import json
import logging
import traceback
from typing import List, Dict, Any

import numpy as np

from app.academic_engine.pdf_engine.pdf_renderer import render_pdf_pages, extract_native_text
from app.academic_engine.pdf_engine.pdf_page_splitter import split_pages
from app.academic_engine.pdf_engine.pdf_quality_optimizer import optimize_page
from app.academic_engine.pdf_engine.multi_page_merger import merge_page_results
from app.academic_engine.pdf_engine.pdf_light_pipeline import run_light_pipeline

logger = logging.getLogger("docvalidator")


def _json_safe(obj):
    """Coerce numpy types so json.dumps never raises."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not serializable: {type(obj)}")


class PDFPipeline:
    """
    Optimised PDF processor — FAST MODE.

    Uses pdf_light_pipeline (PaddleOCR-only, no heavy preprocessing).
    PDFs rendered at 250 DPI — sufficient for clean printed text.
    Memory freed after every page.

    Usage:
        pipeline = PDFPipeline()
        result   = pipeline.process(pdf_bytes, upload_id="abc123")

    Returns the same dict shape as MasterPipeline.process_document().
    """

    def __init__(self):
        # No heavy engine pre-loading — light pipeline imports lazily
        pass

    def process(self, pdf_bytes: bytes, upload_id: str = None) -> dict:
        """
        Full PDF processing:
          render → split → optimize → MasterPipeline (per page) → merge

        Args:
            pdf_bytes: raw PDF file bytes
            upload_id: optional ID for debug artifact naming

        Returns:
            Unified result dict (same schema as image processing result).
        """
        t_start = time.time()
        upload_id = upload_id or str(uuid.uuid4())[:8]

        logger.info("[pdf_pipeline] Starting PDF processing upload_id=%s size=%d",
                    upload_id, len(pdf_bytes))

        # ── STEP 1: Extract native embedded text ─────────────────────────
        native_text_full = ""
        try:
            native_text_full = extract_native_text(pdf_bytes)
            logger.info("[pdf_pipeline] Native text extracted: %d chars", len(native_text_full))
        except Exception as exc:
            logger.warning("[pdf_pipeline] Native text extraction failed: %s", exc)

        # ── STEP 2: Render PDF pages at 400 DPI ──────────────────────────
        try:
            rendered_pages = render_pdf_pages(pdf_bytes)
        except Exception as exc:
            logger.error("[pdf_pipeline] Render failed: %s\n%s", exc, traceback.format_exc())
            return self._error_result(upload_id, f"PDF render failed: {exc}")

        if not rendered_pages:
            return self._error_result(upload_id, "PDF produced 0 renderable pages")

        logger.info("[pdf_pipeline] Rendered %d pages", len(rendered_pages))

        # ── STEP 3: Attach native text per page, split pages ─────────────
        # Distribute native text equally (simple split by page count)
        n_pages = len(rendered_pages)
        if native_text_full and n_pages > 1:
            # Rough split by character count
            chunk_size = max(1, len(native_text_full) // n_pages)
            native_per_page = [
                native_text_full[i * chunk_size:(i + 1) * chunk_size]
                for i in range(n_pages)
            ]
        elif native_text_full:
            native_per_page = [native_text_full]
        else:
            native_per_page = [""] * n_pages

        # Attach native text to each rendered page
        for i, rp in enumerate(rendered_pages):
            rp["native_text"] = native_per_page[i] if i < len(native_per_page) else ""

        pages = split_pages(rendered_pages)
        non_blank = [p for p in pages if not p.get("is_blank", False)]

        if not non_blank:
            return self._error_result(upload_id, "All PDF pages are blank")

        logger.info("[pdf_pipeline] %d non-blank pages to process", len(non_blank))

        # ── STEP 4: Optimize each page + run LIGHT pipeline (sequential) ──
        page_results: List[Dict[str, Any]] = []

        for page in non_blank:
            page_num = page["page_number"]
            page_img = page.get("image")

            try:
                # Light quality optimization (brightness + contrast only)
                optimized = optimize_page(
                    page,
                    native_text=page.get("native_text", ""),
                )
                img = optimized["rendered_image"]

                logger.info(
                    "[pdf_pipeline] LIGHT MODE page %d/%d quality=%.3f scanned=%s size=%dx%d",
                    page_num, len(non_blank),
                    optimized["quality_score"], optimized["is_scanned"],
                    img.shape[1], img.shape[0],
                )

                # ── LIGHT pipeline: PaddleOCR-only, no heavy stages ──────
                page_upload_id = f"{upload_id}_p{page_num}"
                page_native_text = page.get("native_text", "")
                result = run_light_pipeline(img, upload_id=page_upload_id,
                                            native_text=page_native_text)

                page_results.append({
                    "page_number": page_num,
                    "role":        page.get("role", "general"),
                    "quality":     optimized["quality_score"],
                    "is_scanned":  optimized["is_scanned"],
                    "result":      result,
                })

                logger.info(
                    "[pdf_pipeline] Page %d result: status=%s fields=%d",
                    page_num, result.get("status", "?"),
                    len(result.get("valid_fields", {})),
                )

            except Exception as exc:
                logger.error(
                    "[pdf_pipeline] Page %d processing failed: %s\n%s",
                    page_num, exc, traceback.format_exc(),
                )
                # Don't abort — continue with remaining pages
            finally:
                # ── Free page image memory immediately ──────────────────
                if page_img is not None:
                    del page_img
                gc.collect()

        if not page_results:
            return self._error_result(upload_id, "PDF light pipeline failed on all pages")

        # ── STEP 5: Merge multi-page results ─────────────────────────────
        merged = merge_page_results(page_results, upload_id=upload_id)

        # ── Finalise timing ───────────────────────────────────────────────
        elapsed = round(time.time() - t_start, 2)
        merged.setdefault("telemetry", {})
        merged["telemetry"]["pdf_total_time_seconds"] = elapsed
        merged["telemetry"]["pdf_pages_processed"]    = len(page_results)
        merged["telemetry"]["pdf_page_roles"] = [
            {"page": pr["page_number"], "role": pr["role"]} for pr in page_results
        ]
        merged["upload_id"] = upload_id

        # Safe serialization
        try:
            merged = json.loads(json.dumps(merged, default=_json_safe))
        except Exception as exc:
            logger.warning("[pdf_pipeline] JSON serialization warning: %s", exc)

        logger.info(
            "[pdf_pipeline] Done upload_id=%s pages=%d elapsed=%.2fs status=%s",
            upload_id, len(page_results), elapsed, merged.get("status", "?"),
        )

        return merged

    @staticmethod
    def _error_result(upload_id: str, message: str) -> dict:
        return {
            "status":       "error",
            "upload_id":    upload_id,
            "message":      message,
            "valid_fields": {},
            "rejected_fields": {},
            "warnings":     [message],
            "extracted_data": {"fields": {}, "table_data": {}},
            "telemetry": {
                "total_time_seconds": 0,
                "stage_trace": {},
                "warnings": [message],
            },
            "debug_lab": {"pdf_pipeline": {"error": message}},
        }
