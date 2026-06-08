from typing import List, Dict, Any

class ConfidenceEngine:
    def calculate_confidence(self, results: Dict[str, Any], extracted_nodes: List[Any]) -> float:
        conf_score = 0.0
        max_score = 100.0
        
        if results.get("candidate_name"):
            conf_score += 25
        if results.get("percentage") or results.get("cgpa"):
            conf_score += 35
        if results.get("result"):
            conf_score += 20
        if results.get("board"):
            conf_score += 20
            
        return min(max_score, conf_score)
