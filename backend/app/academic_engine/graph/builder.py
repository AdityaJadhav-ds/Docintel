from typing import List, Dict, Any
from ..models import OCRToken

class GraphBuilder:
    def build(self, tokens: List[OCRToken]) -> Dict[str, Any]:
        tokens.sort(key=lambda t: t.y)
        current_row = 0
        current_y = tokens[0].y if tokens else 0
        
        for t in tokens:
            if abs(t.y - current_y) > 15:
                current_row += 1
                current_y = t.y
            t.row_id = current_row
            
        graph = {"nodes": {t.node_id: t for t in tokens}, "edges": {}}
        
        for t in tokens:
            same_row = [n for n in tokens if n.row_id == t.row_id and n.node_id != t.node_id]
            same_row.sort(key=lambda n: n.x)
            right_nodes = [n for n in same_row if n.x > t.x + t.w]
            nearest_right = right_nodes[0].node_id if right_nodes else None
            
            graph["edges"][t.node_id] = {
                "same_row": [n.node_id for n in same_row],
                "nearest_right": nearest_right
            }
        return graph
