import re
from typing import List, Dict, Any
from .models import OCRNode

class CandidateNameEngine:
    def extract(self, nodes: List[OCRNode], anchors: List[Any], graph: Dict[str, Any]) -> str:
        name_anchors = [a for a in anchors if a.anchor_type == "NAME"]
        if not name_anchors:
            return None
            
        anchor = name_anchors[0]
        
        candidates = []
        for node in nodes:
            if node.node_id == anchor.node_id:
                continue
                
            if node.bbox.x_min > anchor.bbox.x_max and abs(node.bbox.y_min - anchor.bbox.y_min) < 30:
                candidates.append(node)
            elif node.bbox.y_min > anchor.bbox.y_max and node.bbox.y_min - anchor.bbox.y_max < 50 and abs(node.bbox.x_min - anchor.bbox.x_min) < 100:
                candidates.append(node)
                
        valid_words = []
        for cand in candidates:
            text = cand.text
            if re.match(r'^[A-Z][A-Z\s]+$', text.upper()) and len(text) > 2:
                if "BOARD" not in text.upper() and "MAHARASHTRA" not in text.upper():
                    valid_words.append(text)
                    
        if valid_words:
            return " ".join(valid_words)
            
        return None
