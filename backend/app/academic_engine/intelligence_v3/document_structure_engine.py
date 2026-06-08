from typing import List
from .models import OCRNode

class DocumentStructureEngine:
    def analyze(self, nodes: List[OCRNode]) -> List[OCRNode]:
        if not nodes:
            return nodes
            
        nodes_sorted_y = sorted(nodes, key=lambda n: n.bbox.y_min)
        
        current_row = 0
        current_y_min = nodes_sorted_y[0].bbox.y_min
        y_tolerance = 15  # pixels
        
        for node in nodes_sorted_y:
            if abs(node.bbox.y_min - current_y_min) > y_tolerance:
                current_row += 1
                current_y_min = node.bbox.y_min
            node.row_id = current_row
            
        return nodes
