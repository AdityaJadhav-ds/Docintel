import re
from typing import List, Dict, Any
from ..models import OCRToken, SemanticAnchor, FieldConfidence
from ..semantics.linker import LabelValueLinker

class MetricParser:
    def __init__(self):
        self.linker = LabelValueLinker()

    def parse(self, metric_type: str, tokens: List[OCRToken], anchors: List[SemanticAnchor], graph: Dict[str, Any]) -> FieldConfidence:
        relevant_anchors = [a for a in anchors if a.anchor_type == metric_type]
        
        valid_candidates = []
        for t in tokens:
            text = t.text
            if metric_type == "PERCENTAGE":
                match = re.search(r'(\d{2}\.\d{2})', text)
                if match:
                    val = float(match.group(1))
                    if 35.0 <= val <= 100.0: valid_candidates.append((val, t))
                else:
                    match_int = re.search(r'^(\d{2,3})$', text)
                    if match_int:
                        val = float(match_int.group(1))
                        if 35.0 <= val <= 100.0: valid_candidates.append((val, t))
            elif metric_type == "CGPA":
                match = re.search(r'^([4-9]\.\d{1,2}|10\.0)$', text)
                if match:
                    valid_candidates.append((float(match.group(1)), t))
                    
        if not valid_candidates:
            return FieldConfidence(value=None, confidence=0.0)
            
        if relevant_anchors:
            best_cand = None
            best_score = -1.0
            source_label = ""
            
            for anchor in relevant_anchors:
                for val, t in valid_candidates:
                    score = self.linker.score_candidate(anchor, t)
                    if abs(t.center_y - anchor.center_y) < 15:
                        score += 50.0
                    
                    if score > best_score:
                        best_score = score
                        best_cand = (val, t)
                        source_label = anchor.text
                        
            if best_cand:
                conf = min(1.0, best_score / 150.0)
                if isinstance(best_cand[0], float) and '.' in str(best_cand[0]):
                    conf = min(1.0, conf + 0.1)
                return FieldConfidence(value=best_cand[0], confidence=conf, source_label=source_label, matched_strategy="semantic_linker")
                
        valid_candidates.sort(key=lambda c: 0 if '.' in c[1].text else 1)
        best = valid_candidates[0]
        return FieldConfidence(value=best[0], confidence=0.4, source_label="document_scan", matched_strategy="fallback_highest_decimal")
