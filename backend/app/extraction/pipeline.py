"""
app/extraction/pipeline.py
===========================
Universal extraction pipeline — the ONLY entry point for OCR.

ONE path:
  upload → render pages → preprocess → ONE PaddleOCR pass → geometry → JSON

NO routing. NO detection. NO handlers. NO adaptive logic.
NO multiple engines. NO retries. NO fallback architecture.

If this file imports anything from old extraction files, something is wrong.

Performance notes (v2):
  - PaddleOCR singleton is PRE-WARMED at module import time so the first
    request does not pay the 15–25s model-load penalty.
  - skip_images=True skips image_to_b64() for the validation path (saves
    50–200ms per page when base64 previews are not needed).
  - Per-stage timing is included in ExtractionResult.metadata.
"""
from __future__ import annotations

import logging
import os
import time
import threading
from typing import Any, Dict, List, Optional

# Disable PaddlePaddle PIR API to fix OneDNN crash on Windows (Python 3.13)
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_enable_pir_in_executor'] = '0'

# Limit OpenMP and underlying BLAS libraries to 1 thread.
# This prevents massive thread thrashing (and OS lockup) when running
# PaddleOCR concurrently in a ThreadPoolExecutor.
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import cv2
import numpy as np

from app.extraction.pdf import render_pages, image_to_b64
from app.extraction.geometry import (
    flatten_paddle_result,
    group_rows,
    cluster_columns,
    extract_transactions,
)
from app.extraction.schemas import ExtractionResult, PageResult

logger = logging.getLogger(__name__)

print("[UNIVERSAL PIPELINE] ACTIVE - paddleocr only, no legacy code")

# ── OCR Engine singletons (thread-safe, initialized once per process) ──────────
#
# TWO singletons, chosen by doc_class:
#
#   KYC  (aadhaar / pan / passport / voter / driving_license)
#        → PP-OCRv3_mobile_det  (2.3MB, ~14s/doc on CPU)
#          Benchmark: identical field extraction, 5.9x faster than server model
#
#   COMPLEX  (bank statements / academic / invoices)
#        → PP-OCRv5_server_det  (84MB, high accuracy for tables & dense text)
#
# Both singletons are initialized lazily on first use and never recreated.

_KYC_DOC_CLASSES = {"kyc"}  # doc_class values that get the mobile detector

_OCR_KYC     = None
_OCR_COMPLEX = None
_OCR_KYC_LOCK     = threading.Lock()
_OCR_COMPLEX_LOCK = threading.Lock()

# ── Predict-level mutex ────────────────────────────────────────────────────────
# Thread safety test (test_ocr_thread_safety.py) proved that concurrent
# predict() calls on a shared PaddleOCR singleton corrupt recognition output
# (recognition buffers are not thread-safe; cross-contamination was observed).
#
# This lock serializes ONLY the predict() call.  Everything else (downloads,
# Supabase saves, review engine, fraud analysis) runs freely in parallel.
# This makes 2-worker concurrent user processing safe without multiprocessing.
_OCR_PREDICT_LOCK = threading.Lock()


def _get_ocr(doc_class: str = "unknown"):
    """Return the appropriate PaddleOCR singleton for the given doc_class.

    KYC documents (aadhaar, pan, passport, voter, driving_license) use the
    mobile detector — benchmark proved identical field extraction at 5.9x speed.
    All other document classes keep the original server detector for maximum
    table/layout accuracy.

    Thread-safe via per-model double-checked locking.
    """
    print(f"[OCR ROUTE] doc_class={doc_class} engine={'KYC(mobile)' if doc_class in _KYC_DOC_CLASSES else 'COMPLEX(server)'}")
    if doc_class in _KYC_DOC_CLASSES:
        global _OCR_KYC
        if _OCR_KYC is not None:
            return _OCR_KYC
        with _OCR_KYC_LOCK:
            if _OCR_KYC is None:
                logger.info(
                    "[pipeline] Initializing KYC OCR engine (PP-OCRv3_mobile_det, thread=%s)...",
                    threading.current_thread().name,
                )
                from paddleocr import PaddleOCR
                _OCR_KYC = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    enable_mkldnn=False,
                    text_detection_model_name="PP-OCRv3_mobile_det",
                    text_recognition_model_name="en_PP-OCRv5_mobile_rec",
                    # Benchmark (bench_rec_batch.py): batch=1 is 33% faster on CPU than
                    # the default batch=6.  On CPU, larger batches thrash L2/L3 cache
                    # with no parallel benefit (unlike GPU).  Fields and confidence
                    # were identical.  Applied to KYC engine only — COMPLEX unchanged.
                    text_recognition_batch_size=1,
                )
                logger.info("[pipeline] KYC OCR engine ready (PP-OCRv3_mobile_det, rec_batch=1).")
        return _OCR_KYC
    else:
        global _OCR_COMPLEX
        if _OCR_COMPLEX is not None:
            return _OCR_COMPLEX
        with _OCR_COMPLEX_LOCK:
            if _OCR_COMPLEX is None:
                logger.info(
                    "[pipeline] Initializing COMPLEX OCR engine (PP-OCRv5_server_det, thread=%s)...",
                    threading.current_thread().name,
                )
                from paddleocr import PaddleOCR
                _OCR_COMPLEX = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    enable_mkldnn=False,
                    lang="en",
                )
                logger.info("[pipeline] COMPLEX OCR engine ready (PP-OCRv5_server_det).")
        return _OCR_COMPLEX


def warmup_ocr() -> None:
    """
    Pre-warm both PaddleOCR engines on a tiny blank image at startup.

    Warms the KYC (mobile) engine first — it is the most frequently used
    path.  The COMPLEX (server) engine is also warmed so bank/academic
    extraction does not pay the load penalty on the first request.
    """
    blank = np.zeros((64, 64, 3), dtype=np.uint8)

    for label, doc_class in [("KYC (mobile)", "kyc"), ("COMPLEX (server)", "unknown")]:
        try:
            logger.info("[pipeline] Pre-warming %s OCR engine...", label)
            t0 = time.monotonic()
            ocr = _get_ocr(doc_class)
            try:
                if hasattr(ocr, "predict"):
                    ocr.predict(blank)
                else:
                    ocr.ocr(blank, cls=False)
            except Exception:
                pass  # blank image → no results, expected
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info("[pipeline] %s OCR engine pre-warm complete in %dms", label, elapsed_ms)
        except Exception as e:
            logger.warning("[pipeline] Pre-warm failed for %s (non-fatal): %s", label, e)


# ── Constants ─────────────────────────────────────────────────────────────────

# For multi-page documents (likely bank statements), crop header/footer.
# Applied ONLY when page_count >= 2.
# Removes logos, address blocks, page headers — speeds up OCR.
CROP_TOP_RATIO    = 0.22   # skip top 22%
CROP_BOTTOM_RATIO = 0.92   # skip below 92%


# ── Public entry point ────────────────────────────────────────────────────────

def universal_extract(
    file_bytes:  bytes,
    filename:    str,
    run_id:      Optional[str] = None,
    skip_images: bool = False,
    doc_class:   str = "unknown",
) -> ExtractionResult:
    """
    Extract text and structured data from any document.

    This is the ONLY extraction function. Called from api/extract.py.
    No other code in the system calls OCR.

    Args:
        file_bytes:   Raw bytes of the uploaded file (PDF, JPG, PNG).
        filename:     Original filename — used for format detection only.
        run_id:       Optional run ID for logging correlation.
        skip_images:  If True, skip image_to_b64() — saves 50–200ms/page
                      when the caller does not need base64 previews
                      (e.g., the validation/KYC save path).
        doc_class:    Document class — controls which OCR engine is used.
                      "kyc"  → PP-OCRv3_mobile_det  (fast, same accuracy)
                      other  → PP-OCRv5_server_det   (original, high accuracy)

    Returns:
        ExtractionResult with pages, transactions, tables, metadata.
    """
    t_start = time.monotonic()
    tag = f"[pipeline run={run_id or 'direct'} doc_class={doc_class}]"
    logger.info("%s START file=%s size=%d skip_images=%s", tag, filename, len(file_bytes), skip_images)

    # ── Timing dict ───────────────────────────────────────────────────────────
    timing: Dict[str, int] = {}

    # ── STEP 1: Render document to images ────────────────────────────────────
    t1 = time.monotonic()
    try:
        page_images: List[np.ndarray] = render_pages(file_bytes, filename)
    except Exception as e:
        logger.error("%s render_pages failed: %s", tag, e)
        raise RuntimeError(f"Failed to render document: {e}") from e

    timing["render_ms"] = int((time.monotonic() - t1) * 1000)
    page_count = len(page_images)
    logger.info("%s rendered %d page(s) in %dms", tag, page_count, timing["render_ms"])

    # ── STEP 2: Get OCR engine (KYC=mobile, other=server) ────────────────────
    t2 = time.monotonic()
    ocr = _get_ocr(doc_class)
    timing["ocr_init_ms"] = int((time.monotonic() - t2) * 1000)

    # ── STEP 3: Per-page processing ───────────────────────────────────────────
    all_page_results: List[PageResult] = []
    all_transactions: List[Dict[str, Any]] = []
    all_tables: List[Dict[str, Any]] = []
    total_words = 0
    total_ocr_ms = 0

    for page_idx, bgr in enumerate(page_images):
        page_tag = f"{tag} page={page_idx}"
        t_page = time.monotonic()

        # STEP 3a: Preprocess — grayscale only (keep it simple)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

        # Optional: light denoising for scanned/photo documents
        # Only apply if image appears noisy (stddev heuristic)
        if _is_noisy(gray):
            gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

        # STEP 3b: Crop header/footer for multi-page documents
        h, w = gray.shape[:2]
        ocr_img = bgr
        y_offset = 0
        if page_count >= 2:
            y1_crop = int(h * CROP_TOP_RATIO)
            y2_crop = int(h * CROP_BOTTOM_RATIO)
            ocr_img = bgr[y1_crop:y2_crop, :]
            y_offset = y1_crop
            logger.debug("%s crop applied: y=%d–%d", page_tag, y1_crop, y2_crop)

        # STEP 3c: ONE PaddleOCR pass — store ALL boxes, never re-run
        t_ocr = time.monotonic()
        try:
            with _OCR_PREDICT_LOCK:          # serialise inference — see note above
                if hasattr(ocr, "predict"):
                    raw_result = ocr.predict(ocr_img)
                else:
                    raw_result = ocr.ocr(ocr_img, cls=False)
        except Exception as e:
            logger.error("%s PaddleOCR failed: %s", page_tag, e)
            raise RuntimeError(f"PaddleOCR execution failed: {e}")

        ocr_ms = int((time.monotonic() - t_ocr) * 1000)
        total_ocr_ms += ocr_ms
        logger.info("%s OCR done in %dms", page_tag, ocr_ms)

        # STEP 3d: Flatten PaddleOCR result → normalized box list
        # PaddleOCR wraps result in extra list for single pages
        flat_result = raw_result
        if flat_result and isinstance(flat_result[0], list):
            flat_result = flat_result[0]

        boxes = flatten_paddle_result(flat_result or [])

        # Re-apply Y-offset if we cropped (so coordinates are page-relative)
        if y_offset > 0:
            for box in boxes:
                box["y1"] += y_offset
                box["y2"] += y_offset
                box["cy"] += y_offset
                for pt in box["bbox"]:
                    pt[1] += y_offset

        logger.info("%s extracted %d boxes", page_tag, len(boxes))

        # STEP 3e: Build page text (reading-order: top→bottom, left→right)
        rows = group_rows(boxes)
        page_text_lines = [" ".join(b["text"] for b in row) for row in rows]
        page_text = "\n".join(page_text_lines)
        page_words = len(page_text.split())
        total_words += page_words

        # STEP 3f: Geometry → table reconstruction
        page_w = float(w)
        col_anchors = cluster_columns(rows, page_width=page_w)
        page_transactions = extract_transactions(rows, col_anchors)

        # Only add transactions if they look structured (≥ 2 columns detected)
        if len(col_anchors) >= 2:
            all_transactions.extend(page_transactions)

            # Build a table object for this page (frontend renders it)
            if page_transactions:
                # Use first record keys (minus "raw") as headers
                sample = page_transactions[0]
                headers = [k for k in sample.keys() if k != "raw"]
                table_rows = [
                    [t.get(h, "") for h in headers]
                    for t in page_transactions
                ]
                all_tables.append({
                    "page": page_idx,
                    "headers": headers,
                    "rows": table_rows,
                    "col_count": len(headers),
                    "engine": "geometry",
                })

        # STEP 3g: Preview image (only when caller needs it)
        # skip_images=True → validation/save path — saves 50–200ms/page
        image_b64 = "" if skip_images else image_to_b64(bgr)

        all_page_results.append(PageResult(
            page_index=page_idx,
            text=page_text,
            boxes=boxes,
            image_b64=image_b64,
        ))

        page_ms = int((time.monotonic() - t_page) * 1000)
        logger.info(
            "%s page done: words=%d boxes=%d cols=%d txns=%d elapsed=%dms",
            page_tag, page_words, len(boxes), len(col_anchors),
            len(page_transactions), page_ms,
        )

    # ── STEP 4: Assemble result ───────────────────────────────────────────────
    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    timing["total_ocr_ms"]   = total_ocr_ms
    timing["total_ms"]       = elapsed_ms

    logger.info(
        "%s DONE: pages=%d words=%d tables=%d transactions=%d elapsed=%dms (ocr=%dms render=%dms)",
        tag, page_count, total_words, len(all_tables), len(all_transactions),
        elapsed_ms, total_ocr_ms, timing.get("render_ms", 0),
    )

    return ExtractionResult(
        pipeline="paddleocr",
        engine="paddleocr",
        metadata={
            "filename": filename,
            "page_count": page_count,
            "total_elapsed_ms": elapsed_ms,
            "timing": timing,
        },
        transactions=all_transactions,
        pages=all_page_results,
        tables=all_tables,
        word_count=total_words,
        elapsed_ms=elapsed_ms,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_noisy(gray: np.ndarray, threshold: float = 18.0) -> bool:
    """
    Simple noise check: if local variance is high, image is likely noisy.
    Returns True if denoising is recommended.
    """
    try:
        # Sample center strip for speed
        h, w = gray.shape[:2]
        strip = gray[h // 4: 3 * h // 4, :]
        laplacian_var = float(cv2.Laplacian(strip, cv2.CV_64F).var())
        # High Laplacian variance = sharp (not noisy). Low = noisy.
        return laplacian_var < threshold
    except Exception:
        return False
