from typing import List, Dict, Any
from .models import OCRNode

class OCRRelationshipGraph:
    def build_graph(self, nodes: List[OCRNode]) -> Dict[str, Any]:
        graph = {
            "nodes": {node.node_id: node for node in nodes},
            "edges": {}
        }
        
        for node in nodes:
            edges = {
                "same_row": [],
                "nearest_right": None,
                "nearest_below": None
            }
            
            same_row = [n for n in nodes if n.row_id == node.row_id and n.node_id != node.node_id]
            edges["same_row"] = [n.node_id for n in same_row]
            
            right_nodes = [n for n in same_row if n.bbox.x_min > node.bbox.x_max]
            if right_nodes:
                nearest_r = min(right_nodes, key=lambda n: n.bbox.x_min - node.bbox.x_max)
                edges["nearest_right"] = nearest_r.node_id
                
            below_nodes = [n for n in nodes if n.bbox.y_min > node.bbox.y_max and abs(n.bbox.x_min - node.bbox.x_min) < 50]
            if below_nodes:
                nearest_b = min(below_nodes, key=lambda n: n.bbox.y_min - node.bbox.y_max)
                edges["nearest_below"] = nearest_b.node_id
                
            graph["edges"][node.node_id] = edges
            
        return graph
