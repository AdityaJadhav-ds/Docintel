"""
app/academic_engine/scanner/__init__.py
=======================================
Academic Document Scanner Engine — Step 1.

Converts ANY uploaded marksheet/certificate into a clean scanner-quality
document BEFORE OCR. This is the foundational restoration layer.

Pipeline order:
  1. boundary_detector    — Crop actual document, remove background
  2. perspective_corrector — Fix tilt / trapezoid / skew
  3. shadow_remover       — Remove shadows, uneven lighting
  4. background_cleaner   — Normalise paper white, reduce watermarks
  5. super_resolution     — Upscale to ≥ 300 DPI equivalent
  6. document_enhancer    — Sharpen text, denoise WhatsApp artefacts
  7. quality_analyzer     — Score result before returning
  8. scan_pipeline        — Orchestrator for the full flow
"""

__version__ = "1.0.0"
