from typing import List, Dict, Any
from .models import OCRNode

class BoardDetector:
    def extract(self, nodes: List[OCRNode], anchors: List[Any], graph: Dict[str, Any]) -> str:
        board_keywords = ["MAHARASHTRA", "PUNE", "UNIVERSITY", "CBSE", "ICSE", "BOARD"]
        
        nodes_sorted = sorted(nodes, key=lambda n: n.bbox.y_min)
        top_nodes = nodes_sorted[:20]
        
        board_text = []
        for node in top_nodes:
            text = node.text.upper()
            if any(kw in text for kw in board_keywords):
                board_text.append(node.text)
                
        if board_text:
            return " ".join(board_text)
            
        return None
