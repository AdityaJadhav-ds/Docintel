import re
from typing import List, Tuple, Optional
from .relationship_graph import DocumentGraph, LineNode

ANCHORS = {
    "percentage": ["percentage", "%", "percentage of marks", "pcnt", "per"],
    "cgpa": ["cgpa", "sgpa", "grade point", "gpa"],
    "result": ["result", "pass", "distinction", "first class", "second class", "fail", "final result", "status"],
    "name": ["candidate name", "full name", "name of candidate", "name", "this is to certify that", "shri", "smt", "kumari"],
    "year": ["passing year", "examination year", "month & year", "year of passing", "year"]
}

def find_anchors(graph: DocumentGraph, anchor_type: str) -> List[LineNode]:
    keywords = ANCHORS.get(anchor_type, [])
    found_lines = []
    
    for line in graph.lines:
        text_lower = line.text.lower()
        if any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in keywords) or \
           any(kw in text_lower for kw in keywords if kw == "%"):
            found_lines.append(line)
            
    return found_lines
