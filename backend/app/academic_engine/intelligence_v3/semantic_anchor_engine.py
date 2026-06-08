from typing import List
from .models import OCRNode, SemanticAnchor

class SemanticAnchorEngine:
    def __init__(self):
        self.anchor_keywords = {
            "NAME": ["candidate name", "full name", "surname first", "name", "candidate's name"],
            "PERCENTAGE": ["percentage", "%", "percentage of marks"],
            "CGPA": ["cgpa", "sgpa", "grade point"],
            "RESULT": ["pass", "result", "distinction", "fail", "class", "grade"],
            "YEAR": ["march", "february", "year", "examination"]
        }
        
    def detect_anchors(self, nodes: List[OCRNode]) -> List[SemanticAnchor]:
        anchors = []
        for node in nodes:
            text_lower = node.text.lower()
            for anchor_type, keywords in self.anchor_keywords.items():
                if any(kw in text_lower for kw in keywords):
                    anchors.append(SemanticAnchor(
                        anchor_type=anchor_type,
                        text=node.text,
                        node_id=node.node_id,
                        bbox=node.bbox
                    ))
        return anchors
