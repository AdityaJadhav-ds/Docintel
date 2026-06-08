"""
app/pdf/scanned_detector.py — PDF type classifier
===================================================
Determines whether a PDF is:
  - DIGITAL: has a text layer (selectable text)
  - SCANNED: image-only (no text layer)
  - HYBRID:  some pages digital, some scanned

Uses text quality from text_extractor to make the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from app.core.logger import logger
from app.pdf.text_extractor import PageText


class PdfType(str, Enum):
    DIGITAL = "digital"    # All/most pages have embedded text
    SCANNED = "scanned"    # No text layer — image only
    HYBRID  = "hybrid"     # Mixed: some digital, some scanned


@dataclass
class PdfClassification:
    pdf_type: PdfType
    total_pages: int
    digital_pages: int
    scanned_pages: int
    overall_quality: float       # avg quality score across all pages
    use_direct_extraction: bool  # True → use text, False → use OCR


def classify_pdf(page_texts: List[PageText]) -> PdfClassification:
    """
    Classify a PDF as DIGITAL, SCANNED, or HYBRID based on extracted page texts.

    Args:
        page_texts: output of text_extractor.extract_pdf_text()

    Returns:
        PdfClassification with recommendation (use_direct_extraction)
    """
    if not page_texts:
        logger.info("[scanned_detector] No pages — treating as SCANNED")
        return PdfClassification(
            pdf_type=PdfType.SCANNED,
            total_pages=0,
            digital_pages=0,
            scanned_pages=0,
            overall_quality=0.0,
            use_direct_extraction=False,
        )

    total   = len(page_texts)
    digital = sum(1 for p in page_texts if p.is_digital)
    scanned = total - digital
    avg_q   = sum(p.quality_score for p in page_texts) / total

    # Classification logic
    if digital == 0:
        pdf_type = PdfType.SCANNED
    elif digital == total:
        pdf_type = PdfType.DIGITAL
    else:
        pdf_type = PdfType.HYBRID

    # Use direct extraction if MORE THAN HALF of pages are digital
    use_direct = digital >= max(1, total // 2)

    logger.info(
        "[scanned_detector] PDF type=%s total=%d digital=%d scanned=%d "
        "avg_quality=%.2f use_direct=%s",
        pdf_type.value, total, digital, scanned, avg_q, use_direct
    )

    return PdfClassification(
        pdf_type=pdf_type,
        total_pages=total,
        digital_pages=digital,
        scanned_pages=scanned,
        overall_quality=round(avg_q, 4),
        use_direct_extraction=use_direct,
    )
