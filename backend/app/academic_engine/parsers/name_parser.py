import re
from typing import List, Dict, Any
from ..models import OCRToken, SemanticAnchor, FieldConfidence
from ..semantics.linker import LabelValueLinker

class NameParser:
    def __init__(self):
        self.linker = LabelValueLinker()

    def parse(self, target: str, tokens: List[OCRToken], anchors: List[SemanticAnchor], graph: Dict[str, Any]) -> FieldConfidence:
        relevant_anchors = [a for a in anchors if a.anchor_type == target]
        if not relevant_anchors:
            return FieldConfidence(value=None, confidence=0.0)
            
        best_overall_cand = None
        best_overall_score = 0.0
        source_label = ""
        
        for anchor in relevant_anchors:
            candidates = []
            for t in tokens:
                if t.node_id == anchor.node_id: continue
                if t.x1 > anchor.x2 - 50 and abs(t.y1 - anchor.y1) < 50 or \
                   t.y1 > anchor.y2 - 20 and t.y1 - anchor.y2 < 100 and abs(t.x1 - anchor.x1) < 200:
                    candidates.append(t)
                    
            for c in candidates:
                text = c.text
                base_score = self.linker.score_candidate(anchor, c)
                
                words = text.split()
                if 2 <= len(words) <= 5: base_score += 30
                if text.istitle() or text.isupper(): base_score += 20
                if re.match(r'^[A-Za-z\s\.]+$', text): base_score += 30
                if "BOARD" in text.upper() or "SUBJECT" in text.upper() or "SECONDARY" in text.upper(): base_score -= 100
                if any(char.isdigit() for char in text): base_score -= 50
                
                if base_score > best_overall_score:
                    best_overall_score = base_score
                    best_overall_cand = c
                    source_label = anchor.text
                    
        if best_overall_cand and best_overall_score > 0:
            conf = min(1.0, best_overall_score / 150.0)
            return FieldConfidence(value=best_overall_cand.text, confidence=conf, source_label=source_label, matched_strategy="semantic_linker")
            
        return FieldConfidence(value=None, confidence=0.0)
