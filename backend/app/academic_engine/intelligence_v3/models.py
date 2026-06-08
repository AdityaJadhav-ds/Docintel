from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple

class BBox(BaseModel):
    x_min: int
    y_min: int
    x_max: int
    y_max: int

class OCRNode(BaseModel):
    text: str
    confidence: float
    bbox: BBox
    engine: str = "unknown"
    node_id: str = ""
    row_id: Optional[int] = None
    column_id: Optional[int] = None
    line_id: Optional[int] = None

class SemanticAnchor(BaseModel):
    anchor_type: str
    text: str
    node_id: str
    bbox: BBox
