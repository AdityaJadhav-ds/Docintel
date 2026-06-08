"""
app/ocr/detector.py
=====================
Compatibility shim for document type detection.
"""
from __future__ import annotations
from typing import Dict, Optional


def detect_document_type(text: str, hint: Optional[str] = None) -> Dict:
    """Detect document type from text content."""
    from app.extraction.semantic_cleaner import detect_doc_type
    return detect_doc_type(text, hint=hint)
