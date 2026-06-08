"""
app/extraction/doc_router.py
=============================
Document type detector + pipeline parameter selector.

Detects document type from:
  1. Filename keywords
  2. File content (first 4 bytes for PDF detection)
  3. First-pass text keyword scan (if needed)

Returns pipeline configuration:
  - timeout_sec     : per-request hard timeout
  - skip_images     : whether to generate base64 page previews
  - doc_class       : "kyc" | "academic" | "bank" | "complex_table" | "unknown"
  - doc_type        : specific type string
  - log_tag         : short label for logging

NO OCR is run here. This is a lightweight pre-routing step only.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Any


# ── Document class → pipeline parameters ─────────────────────────────────────
_PIPELINE_PARAMS: Dict[str, Dict[str, Any]] = {
    # KYC: single-page images, fast path
    "kyc": {
        "timeout_sec":   45,
        "skip_images":   False,   # keep images for preview
        "doc_class":     "kyc",
        "log_tag":       "KYC",
    },
    # Academic: multi-page PDFs with tables
    "academic": {
        "timeout_sec":   90,
        "skip_images":   False,
        "doc_class":     "academic",
        "log_tag":       "ACADEMIC",
    },
    # Bank statements: many pages, heavy tables, no preview needed in pipeline
    "bank": {
        "timeout_sec":   300,
        "skip_images":   True,    # skip b64 encoding — validation path discards it
        "doc_class":     "bank",
        "log_tag":       "BANK",
    },
    # Complex tables (invoices): moderate
    "invoice": {
        "timeout_sec":   120,
        "skip_images":   False,
        "doc_class":     "invoice",
        "log_tag":       "INVOICE",
    },
    # Fallback for unknown types
    "unknown": {
        "timeout_sec":   120,
        "skip_images":   False,
        "doc_class":     "unknown",
        "log_tag":       "UNKNOWN",
    },
}

# ── Keyword maps (lowercase filename substrings → doc class) ─────────────────
_FILENAME_KEYWORDS: Dict[str, str] = {
    # KYC
    "aadhaar":      "kyc",
    "aadhar":       "kyc",
    "uid":          "kyc",
    "pan":          "kyc",
    "passport":     "kyc",
    "dl":           "kyc",
    "driving":      "kyc",
    "voter":        "kyc",
    "license":      "kyc",
    "licence":      "kyc",
    # Academic
    "marksheet":    "academic",
    "markcard":     "academic",
    "transcript":   "academic",
    "degree":       "academic",
    "certificate":  "academic",
    "diploma":      "academic",
    "result":       "academic",
    "grades":       "academic",
    "ssc":          "academic",
    "hsc":          "academic",
    "tenth":        "academic",
    "twelfth":      "academic",
    "semester":     "academic",
    "resume":       "academic",
    "cv":           "academic",
    # Bank / Finance
    "bank":         "bank",
    "statement":    "bank",
    "account":      "bank",
    "passbook":     "bank",
    # Invoice
    "invoice":      "invoice",
    "bill":         "invoice",
    "receipt":      "invoice",
}

# ── Specific doc type name map (keyword → doc_type string) ───────────────────
_DOC_TYPE_NAMES: Dict[str, str] = {
    "aadhaar":  "aadhaar",
    "aadhar":   "aadhaar",
    "uid":      "aadhaar",
    "pan":      "pan",
    "passport": "passport",
    "driving":  "driving_license",
    "dl":       "driving_license",
    "voter":    "voter_id",
    "bank":     "bank_statement",
    "statement":"bank_statement",
    "invoice":  "invoice",
    "marksheet":"marksheet",
    "transcript":"transcript",
    "degree":   "degree_certificate",
    "diploma":  "diploma",
    "resume":   "resume",
    "cv":       "resume",
}


def detect(filename: str, file_bytes: bytes) -> Dict[str, Any]:
    """
    Detect document class and type from filename and file bytes.

    Returns a pipeline configuration dict. Always returns a valid dict —
    never raises.

    Args:
        filename:   Original filename (e.g. "aadhaar_scan.pdf")
        file_bytes: Raw file bytes (first 16 bytes are sufficient)

    Returns:
        {
            "doc_class":   str,   # "kyc" | "academic" | "bank" | "invoice" | "unknown"
            "doc_type":    str,   # specific type or "unknown"
            "is_pdf":      bool,
            "timeout_sec": int,
            "skip_images": bool,
            "log_tag":     str,
        }
    """
    name_lower = (filename or "").lower()
    base_name  = os.path.splitext(name_lower)[0]

    # Detect PDF from magic bytes
    is_pdf = file_bytes[:4] == b"%PDF"

    # ── Step 1: Match filename keywords ──────────────────────────────────────
    doc_class = "unknown"
    doc_type  = "unknown"

    for keyword, klass in _FILENAME_KEYWORDS.items():
        if keyword in base_name:
            doc_class = klass
            break

    for keyword, dtype in _DOC_TYPE_NAMES.items():
        if keyword in base_name:
            doc_type = dtype
            break

    # ── Step 2: Refine from file extension heuristic ─────────────────────────
    # Multi-page PDFs with unknown type → assume academic or bank
    if doc_class == "unknown" and is_pdf:
        # Can't know pages without rendering — default to academic timeout
        doc_class = "academic"

    # ── Return full params ────────────────────────────────────────────────────
    params = _PIPELINE_PARAMS.get(doc_class, _PIPELINE_PARAMS["unknown"]).copy()
    params["doc_type"] = doc_type
    params["is_pdf"]   = is_pdf
    return params
