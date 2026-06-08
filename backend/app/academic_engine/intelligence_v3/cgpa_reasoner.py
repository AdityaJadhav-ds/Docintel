import re
from typing import List, Dict, Any
from .models import OCRNode

class CGPAReasoner:
    def extract(self, nodes: List[OCRNode], anchors: List[Any], graph: Dict[str, Any]) -> str:
        cgpa_anchors = [a for a in anchors if a.anchor_type == "CGPA"]
        
        candidates = []
        for node in nodes:
            match = re.search(r'^([0-9]\.\d{1,2}|10\.0)$', node.text)
            if match:
                val = float(match.group(1))
                if 4.0 <= val <= 10.0:
                    candidates.append((val, node))
                    
        if not candidates:
            return None
            
        if cgpa_anchors:
            anchor = cgpa_anchors[0]
            candidates.sort(key=lambda c: abs(c[1].bbox.y_min - anchor.bbox.y_min) + abs(c[1].bbox.x_min - anchor.bbox.x_max))
            return str(candidates[0][0])
            
        return str(candidates[0][0])
