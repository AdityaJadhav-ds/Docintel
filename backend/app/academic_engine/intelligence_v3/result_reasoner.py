from typing import List, Dict, Any
from .models import OCRNode

class ResultReasoner:
    def extract(self, nodes: List[OCRNode], anchors: List[Any], graph: Dict[str, Any]) -> str:
        valid_results = ["PASS", "FAIL", "DISTINCTION", "FIRST CLASS", "SECOND CLASS"]
        
        for node in nodes:
            text = node.text.upper()
            for res in valid_results:
                if res in text:
                    return res
                    
        return None
