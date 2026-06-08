import re
from typing import List, Dict, Any
from .models import OCRNode

class PercentageReasoner:
    def extract(self, nodes: List[OCRNode], anchors: List[Any], graph: Dict[str, Any]) -> str:
        pct_anchors = [a for a in anchors if a.anchor_type == "PERCENTAGE"]
        
        candidates = []
        for node in nodes:
            text = node.text
            match = re.search(r'(\d{2}\.\d{2})', text)
            if match:
                val = float(match.group(1))
                if 35.0 <= val <= 100.0:
                    candidates.append((val, node))
            else:
                match_int = re.search(r'^(\d{2,3})$', text)
                if match_int:
                    val = float(match_int.group(1))
                    if 35.0 <= val <= 100.0:
                        candidates.append((val, node))
                        
        if not candidates:
            return None
            
        if pct_anchors:
            anchor = pct_anchors[0]
            candidates.sort(key=lambda c: abs(c[1].bbox.y_min - anchor.bbox.y_min) + abs(c[1].bbox.x_min - anchor.bbox.x_max))
            return str(candidates[0][0])
            
        candidates.sort(key=lambda c: 0 if '.' in c[1].text else 1)
        return str(candidates[0][0])
