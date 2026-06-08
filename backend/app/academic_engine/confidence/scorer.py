from typing import Dict, Any

class ConfidenceScorer:
    def score_document(self, parsed_data: Dict[str, Any]) -> float:
        total = 0.0
        weights = {
            "candidate_name": 0.3,
            "percentage": 0.2,
            "cgpa": 0.2,
            "board_name": 0.1,
            "document_type": 0.2
        }
        
        for k, weight in weights.items():
            if k in parsed_data and parsed_data[k]:
                conf = parsed_data[k].get("confidence", 0.0) if isinstance(parsed_data[k], dict) else 1.0
                total += weight * conf
                
        return total
