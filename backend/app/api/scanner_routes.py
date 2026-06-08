"""
app/api/scanner_routes.py
==========================
FastAPI routes for the Academic Document Scanner Engine (Step 1).

Endpoints:
  POST /api/v2/scanner/restore
    - Accepts: multipart/form-data with file= (image or PDF)
    - Returns: JSON with original_b64, restored_b64, quality_report, metadata

  GET  /api/v2/scanner/health
    - Returns pipeline health / availability
"""

from __future__ import annotations

import io
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

from app.core.logger import logger

router = APIRouter(prefix="/v2/scanner", tags=["Academic Scanner"])


# ── Lazy pipeline import (avoids cold-start cost) ─────────────────────────────

def _get_pipeline():
    from app.academic_engine.scanner.scan_pipeline import run_scan_pipeline
    return run_scan_pipeline


def _pdf_first_page_bytes(pdf_bytes: bytes) -> bytes:
    """Convert first page of PDF to PNG bytes."""
    try:
        from app.files.pdf_converter import pdf_first_page
        from PIL import Image
        pil = pdf_first_page(pdf_bytes)
        if pil is None:
            raise ValueError("PDF rendered no pages")
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"PDF conversion failed: {exc}")


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/health")
async def scanner_health():
    """Check scanner pipeline availability."""
    try:
        import cv2
        import numpy as np
        from app.academic_engine.scanner.scan_pipeline import run_scan_pipeline
        return {
            "status":   "ok",
            "engine":   "Academic Document Scanner v1.0",
            "opencv":   cv2.__version__,
            "pipeline": "ready",
        }
    except Exception as exc:
        logger.error("[scanner_routes] Health check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": str(exc)},
        )


@router.post("/restore")
async def restore_document(
    file: UploadFile = File(...),
    aggressive: bool = False,
):
    """
    Restore an uploaded document image / PDF to scanner quality.

    Returns:
        {
          "success":        bool,
          "original_b64":   string  (base64 JPEG of input),
          "restored_b64":   string  (base64 JPEG of cleaned output),
          "quality_report": { quality_score, blur_score, brightness_score, ... },
          "stage_metadata": { ... },
          "debug_session":  string,
          "elapsed_ms":     float
        }
    """
    content_type = (file.content_type or "").lower()
    filename     = (file.filename     or "").lower()

    logger.info(
        "[scanner_routes] /restore — file=%s type=%s aggressive=%s",
        file.filename, content_type, aggressive,
    )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Handle PDF: convert first page → image bytes
    if content_type == "application/pdf" or filename.endswith(".pdf") or raw[:4] == b"%PDF":
        raw = _pdf_first_page_bytes(raw)

    run_pipeline = _get_pipeline()

    try:
        result = run_pipeline(raw, aggressive_enhance=aggressive)
    except Exception as exc:
        logger.error("[scanner_routes] Pipeline crashed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Scanner pipeline error: {exc}")

    return JSONResponse(content=result.to_dict())
