"""
academic_engine/pdf_engine
===========================
Production PDF ingestion layer for academic documents.

Converts PDFs into clean images at 250 DPI, then feeds them into the
LIGHT pipeline (PaddleOCR-only, no heavy preprocessing) for fast extraction.

Image pipeline (MasterPipeline) is NOT used for PDFs.
PDFs are already clean — mobile-image recovery logic is for camera images only.

Target: 5–15 seconds per PDF page (vs 90s+ with heavy pipeline).

Public API:
    from app.academic_engine.pdf_engine import PDFPipeline
    result = PDFPipeline().process(pdf_bytes, upload_id)

    from app.academic_engine.pdf_engine import run_light_pipeline
    result = run_light_pipeline(image_np, upload_id)
"""
from .pdf_pipeline import PDFPipeline
from .pdf_light_pipeline import run_light_pipeline

__all__ = ["PDFPipeline", "run_light_pipeline"]
