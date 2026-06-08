"""
app/extraction/__init__.py
===========================
Universal extraction package.
Exports ONLY the public API.
"""
from app.extraction.pipeline import universal_extract
from app.extraction.schemas import ExtractionResult, PageResult

__all__ = ["universal_extract", "ExtractionResult", "PageResult"]
