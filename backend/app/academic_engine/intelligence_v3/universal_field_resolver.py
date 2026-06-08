from typing import List, Dict, Any
from .models import OCRNode, SemanticAnchor

class UniversalFieldResolver:
    def resolve(self, nodes: List[OCRNode], anchors: List[SemanticAnchor], graph: Dict[str, Any], field_engines: Dict[str, Any]) -> Dict[str, Any]:
        results = {}
        
        name_engine = field_engines.get("name")
        if name_engine:
            results["candidate_name"] = name_engine.extract(nodes, anchors, graph)
            
        pct_engine = field_engines.get("percentage")
        if pct_engine:
            results["percentage"] = pct_engine.extract(nodes, anchors, graph)
            
        cgpa_engine = field_engines.get("cgpa")
        if cgpa_engine:
            results["cgpa"] = cgpa_engine.extract(nodes, anchors, graph)
            
        result_engine = field_engines.get("result")
        if result_engine:
            results["result"] = result_engine.extract(nodes, anchors, graph)
            
        board_engine = field_engines.get("board")
        if board_engine:
            results["board"] = board_engine.extract(nodes, anchors, graph)
            
        return results
