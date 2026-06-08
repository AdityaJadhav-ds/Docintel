"""
app/services/ocr_pipeline.py
==============================
KYC document processing shim.

Rewritten to use the universal extraction pipeline instead of the
deleted ocr_router / normalizer / text_reconstructor / semantic_cleaner chain.

Output contract (unchanged — validation_service.py depends on this):
    {
        "doc_type":       str,
        "extracted":      Dict (name, aadhaar_number, pan_number, dob, etc.),
        "ocr_confidence": float,
        "raw_text":       str,
        "clean_text":     str,
        "engines_used":   List[str],
        "variant_texts":  Dict,
    }
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, Optional

try:
    from app.core.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


def process_document(
    image_input,
    doc_type_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a document image or PDF bytes through the universal pipeline.
    Returns KYC-contract-compatible result dict.
    """
    # Read bytes
    if hasattr(image_input, "read"):
        file_bytes = image_input.read()
    elif isinstance(image_input, (bytes, bytearray)):
        file_bytes = bytes(image_input)
    else:
        logger.error("[ocr_pipeline] Invalid input type: %s", type(image_input))
        return _empty_result("unknown")

    if not file_bytes:
        return _empty_result("unknown")

    filename = "document.pdf" if file_bytes[:4] == b"%PDF" else "document.jpg"

    # Map KYC doc types to the fast mobile OCR engine
    _KYC_TYPES = {"aadhaar", "pan", "passport", "driving_license", "voter_id", "kyc"}
    doc_class = "kyc" if (doc_type_hint or "").lower() in _KYC_TYPES else "unknown"

    try:
        from app.extraction.pipeline import universal_extract

        result = universal_extract(file_bytes, filename, doc_class=doc_class)

        full_text = "\n\n".join(p.text for p in result.pages)
        avg_conf = 0.0
        all_boxes = [box for p in result.pages for box in p.boxes]
        if all_boxes:
            avg_conf = sum(b.get("confidence", 0.0) for b in all_boxes) / len(all_boxes)

        doc_type = doc_type_hint or _detect_doc_type(full_text)
        extracted = _extract_kyc_fields(full_text, doc_type)

        return {
            "doc_type":       doc_type,
            "extracted":      extracted,
            "ocr_confidence": round(avg_conf, 3),
            "raw_text":       full_text,
            "clean_text":     full_text,
            "engines_used":   ["paddleocr"],
            "variant_texts":  {"primary": full_text},
        }

    except Exception as exc:
        logger.error("[ocr_pipeline] Failed: %s", exc, exc_info=True)
        return _empty_result(doc_type_hint or "unknown")


def _detect_doc_type(text: str) -> str:
    """Simple keyword-based document type detection."""
    text_lower = text.lower()
    if any(w in text_lower for w in ("aadhaar", "unique identification", "uid")):
        return "aadhaar"
    if any(w in text_lower for w in ("permanent account", " pan ", "income tax")):
        return "pan"
    if any(w in text_lower for w in ("passport", "republic of india", "passport no")):
        return "passport"
    if any(w in text_lower for w in ("driving licence", "driving license", "dl no")):
        return "driving_license"
    if any(w in text_lower for w in ("account statement", "statement of account", "bank statement")):
        return "bank_statement"
    return "unknown"


def _extract_kyc_fields(text: str, doc_type: str) -> Dict[str, Any]:
    """Extract KYC fields from OCR text using regex."""
    extracted: Dict[str, Any] = {}

    # Name
    name_match = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text)
    if name_match:
        extracted["name"] = name_match.group(1)

    # Aadhaar (12 digits, may be space/dash separated)
    aadhaar_match = re.search(r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b", text)
    if aadhaar_match:
        extracted["aadhaar_number"] = re.sub(r"[\s\-]", "", aadhaar_match.group(1))

    # PAN (AAAAA9999A format)
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text)
    if pan_match:
        extracted["pan_number"] = pan_match.group(1)

    # DOB
    dob_match = re.search(
        r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{2}\s+\w{3}\s+\d{4})\b",
        text
    )
    if dob_match:
        extracted["dob"] = dob_match.group(1)

    # Phone
    phone_match = re.search(r"\b([6-9]\d{9})\b", text)
    if phone_match:
        extracted["phone"] = phone_match.group(1)

    # Address
    addr_match = re.search(
        r"(?:Address|Addr)[:\s]+(.{10,200}?)(?:\n{2,}|$)",
        text, re.IGNORECASE | re.DOTALL
    )
    if addr_match:
        extracted["address"] = addr_match.group(1).strip().replace("\n", ", ")

    return extracted


def _empty_result(doc_type: str) -> Dict[str, Any]:
    return {
        "doc_type":       doc_type,
        "extracted":      {},
        "ocr_confidence": 0.0,
        "raw_text":       "",
        "clean_text":     "",
        "engines_used":   [],
        "variant_texts":  {},
    }
