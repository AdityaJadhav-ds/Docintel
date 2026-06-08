"""
app/extraction/schemas.py
==========================
Clean data schemas for the universal extraction pipeline.
ONE schema, ONE path.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PageResult:
    """OCR result for a single page."""
    page_index: int
    text: str
    boxes: List[Dict[str, Any]]   # raw PaddleOCR boxes [{text, confidence, bbox}]
    image_b64: str                # base64 JPEG preview for frontend


@dataclass
class ExtractionResult:
    """
    Universal extraction result returned by universal_extract().
    This is the ONLY result shape in the system.
    """
    pipeline: str = "universal"
    metadata: Dict[str, Any] = field(default_factory=dict)
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    pages: List[PageResult] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    word_count: int = 0
    elapsed_ms: int = 0
    engine: str = "paddleocr"

    def to_api_dict(self) -> Dict[str, Any]:
        """
        Serialize to the JSON shape the frontend expects.
        ExtractionStudio.jsx reads:
          result.pipeline, result.ocr.raw_text, result.ocr.word_count,
          result.transactions, result.tables, result.blocks,
          result.images.pages, result.meta.page_count,
          result.meta.total_elapsed_ms
        """
        full_text = "\n\n".join(p.text for p in self.pages)
        page_images = [p.image_b64 for p in self.pages]

        # Build flat blocks list from page boxes for the exact-layout overlay
        blocks: List[Dict] = []
        for p in self.pages:
            for box in p.boxes:
                bbox = box.get("bbox", [[0, 0], [0, 0], [0, 0], [0, 0]])
                x1 = float(bbox[0][0])
                y1 = float(bbox[0][1])
                x2 = float(bbox[2][0])
                y2 = float(bbox[2][1])
                blocks.append({
                    "type": "paragraph",
                    "content": box.get("text", ""),
                    "text": box.get("text", ""),
                    "confidence": box.get("confidence", 0.0),
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "page": p.page_index,
                    "engine": "paddleocr",
                })

        return {
            "success": True,
            "pipeline": self.pipeline,
            "engine": self.engine,
            "meta": {
                "filename": self.metadata.get("filename", ""),
                "page_count": len(self.pages),
                "total_elapsed_ms": self.elapsed_ms,
                "pipeline": self.pipeline,
                "phase": "universal_v1",
            },
            "ocr": {
                "raw_text": full_text,
                "clean_text": full_text,
                "human_readable": full_text,
                "word_count": self.word_count,
                "engines_used": [self.engine],
                "pipeline_label": "Universal Pipeline — PaddleOCR",
                "pages": [p.text for p in self.pages],
                "page_boxes": [p.boxes for p in self.pages],
            },
            "metadata": self.metadata,
            "transactions": self.transactions,
            "tables": self.tables,
            "blocks": blocks,
            "images": {
                "pages": page_images,
                "original": page_images[0] if page_images else "",
            },
            "quality": {
                "overall": 85 if self.word_count > 10 else 20,
                "grade": "B" if self.word_count > 10 else "F",
                "word_count": self.word_count,
            },
            "page_dims": {"width": 794, "height": 1123},
            "page_count": len(self.pages),
            "document_type": "document",
            "word_count": self.word_count,
        }
