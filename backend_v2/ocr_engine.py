"""
ocr_engine.py — PaddleOCR Singleton

Safe optimizations applied (zero accuracy impact):

  use_angle_cls=False  — skip rotation classifier; upright docs only (A4, bank statements)
  lang='en'            — English dict only; no multilingual overhead
  rec_batch_num=16     — recognise 16 boxes at once vs default 6; pure throughput win
  use_gpu=False        — CPU inference; deterministic, no CUDA dependency
  show_log=False       — suppress Paddle verbose stdout

DELIBERATELY NOT SET:
  det_limit_side_len   — left at Paddle default (960). Reducing this caused word-count
                         regression (734→673 words). Detection resolution must stay high
                         for dense bank-statement text.

Thread pinning (OMP_NUM_THREADS / MKL_NUM_THREADS) is set in main.py
before this module is imported.
"""
import logging

logger = logging.getLogger(__name__)
_OCR_INSTANCE = None


def get_ocr_engine():
    """
    Returns the global singleton PaddleOCR instance, initialised lazily.
    Never recreated after first load — inference graph stays warm across all requests.
    """
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        logger.info("Initializing PaddleOCR singleton…")
        from paddleocr import PaddleOCR

        _OCR_INSTANCE = PaddleOCR(
            # ── Accuracy settings (DO NOT CHANGE) ─────────────────────────────
            use_angle_cls=False,   # upright docs: cls is pure overhead
            lang='en',             # English-only dict
            use_gpu=False,         # CPU inference — stable, reproducible

            # ── Safe throughput improvement ────────────────────────────────────
            rec_batch_num=16,      # recognition batch: 6→16 (no accuracy impact)

            # ── Misc ──────────────────────────────────────────────────────────
            show_log=False,
        )
        logger.info("PaddleOCR singleton ready.")

    return _OCR_INSTANCE


def extract_text_from_image(img_array):
    """
    Runs OCR on a numpy BGR image array.
    cls=False: skip per-call angle check (already disabled globally).
    """
    ocr = get_ocr_engine()
    result = ocr.ocr(img_array, cls=False)
    return result
