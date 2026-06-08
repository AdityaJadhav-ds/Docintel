"""
layout_tree.py — Canonical Document Structure Models

Defines the exact structure of the visual document hierarchy:
Document ├── Page ├── Region ├── Line ├── Word
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class Word:
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    cx: float
    cy: float
    width: float
    height: float

    def to_dict(self):
        return asdict(self)

@dataclass
class Line:
    line_id: int
    words: List[Word]
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    cy: float
    visual_lines: List[Any] = field(default_factory=list)
    region_type: str = "paragraph"

    def to_dict(self):
        return asdict(self)

@dataclass
class Region:
    region_id: int
    region_type: str  # "header", "kv_block", "paragraph", "table", "footer"
    lines: List[Line]
    content: Any = None  # Generic payload (e.g. table grid arrays, KV pairs)
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0

    def to_dict(self):
        d = asdict(self)
        d["lines"] = [l.to_dict() if isinstance(l, Line) else l for l in self.lines]
        return d

@dataclass
class Page:
    page_number: int
    width: int
    height: int
    words: List[Word] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)
    regions: List[Region] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

@dataclass
class Document:
    title: str = "Extracted Document"
    metadata: Dict[str, str] = field(default_factory=dict)
    pages: List[Page] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
