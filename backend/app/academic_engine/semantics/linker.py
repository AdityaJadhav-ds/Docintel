import math
from typing import List, Dict, Any, Tuple
from ..models import OCRToken, SemanticAnchor

class LabelValueLinker:
    def score_candidate(self, anchor: SemanticAnchor, token: OCRToken) -> float:
        score = 0.0
        
        dist = math.hypot(token.center_x - anchor.center_x, token.center_y - anchor.center_y)
        if dist < 500:
            distance_score = 40.0 * (1.0 - (dist / 500.0))
        else:
            distance_score = 0.0
        score += distance_score
            
        align_score = 0.0
        if abs(token.center_y - anchor.center_y) < 20: 
            align_score = 10.0
            if token.x1 > anchor.x2: 
                align_score += 10.0
        elif abs(token.center_x - anchor.center_x) < 50: 
            align_score = 10.0
            if token.y1 > anchor.y2: 
                align_score += 10.0
        score += align_score
        
        if hasattr(token, 'line_id') and hasattr(anchor, 'line_id') and getattr(token, 'line_id', -1) == getattr(anchor, 'line_id', -2):
            score += 10.0
        if hasattr(token, 'row_id') and hasattr(anchor, 'row_id') and getattr(token, 'row_id', -1) == getattr(anchor, 'row_id', -2):
            score += 10.0
            
        height_diff = abs((token.y2 - token.y1) - (anchor.y2 - anchor.y1))
        if height_diff < 5:
            score += 10.0
            
        if anchor.anchor_type == "PERCENTAGE" and "%" in token.text:
            score += 20.0
            
        return score
