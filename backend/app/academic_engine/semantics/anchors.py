from typing import List, Dict
from ..models import OCRToken, SemanticAnchor

class SemanticAnchorEngine:
    ANCHORS = {
        "CANDIDATE_NAME": ["candidate name", "full name", "name", "certify that", "mr.", "ms.", "mrs.", "student name"],
        "MOTHER_NAME": ["mother's name", "mother name", "mother"],
        "FATHER_NAME": ["father's name", "father name", "father"],
        "PERCENTAGE": ["percentage", "aggregate", "%", "percent", "total percentage"],
        "CGPA": ["cgpa", "sgpa", "spi", "cpi"],
        "RESULT": ["result", "grade", "class", "pass", "fail", "distinction", "division"],
        "TOTAL_MARKS": ["total marks", "maximum marks", "max marks"],
        "OBTAINED_MARKS": ["marks obtained", "obtained marks", "secured"],
        "BOARD": ["board", "university", "autonomous", "college"]
    }
    
    def detect(self, tokens: List[OCRToken]) -> List[SemanticAnchor]:
        detected = []
        for t in tokens:
            text_lower = t.text.lower()
            for a_type, kws in self.ANCHORS.items():
                if any(kw in text_lower for kw in kws):
                    detected.append(SemanticAnchor(
                        anchor_type=a_type, text=t.text, node_id=t.node_id,
                        x1=t.x1, y1=t.y1, x2=t.x2, y2=t.y2,
                        center_x=t.center_x, center_y=t.center_y
                    ))
        return detected
