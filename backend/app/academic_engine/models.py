from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class OCRToken(BaseModel):
    text: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    center_x: float = 0.0
    center_y: float = 0.0
    line_id: int = 0
    block_id: int = 0
    row_id: int = 0
    col_id: int = 0
    engine: str = "unknown"
    node_id: str = ""

class SemanticAnchor(BaseModel):
    anchor_type: str
    text: str
    node_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    center_x: float = 0.0
    center_y: float = 0.0

class FieldConfidence(BaseModel):
    value: Any
    confidence: float
    source_label: str = ""
    matched_strategy: str = ""
