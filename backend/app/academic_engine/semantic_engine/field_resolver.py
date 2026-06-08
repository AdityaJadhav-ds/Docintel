from .candidate_ranker import CandidateRanker
from .extraction_confidence import ExtractionConfidence

class FieldResolver:
    """Step 11: Candidate selection and fallback strategies"""
    
    def __init__(self, ranker: CandidateRanker, conf_engine: ExtractionConfidence):
        self.ranker = ranker
        self.conf_engine = conf_engine
        
    def resolve_name(self, candidates: list) -> tuple:
        best_candidate = None
        best_score = -999.0
        rejected = []
        
        for cand in candidates:
            score = self.ranker.score_name_candidate(cand['value'])
            if score > best_score:
                if best_candidate:
                    rejected.append(best_candidate)
                best_score = score
                best_candidate = cand
            else:
                rejected.append(cand)
                
        return best_candidate, best_score, rejected
        
    def resolve_percentage(self, candidates: list, graph) -> tuple:
        best_candidate = None
        best_score = -999.0
        rejected = []
        
        for cand in candidates:
            score = self.ranker.score_percentage_candidate(cand['value'], cand['node'], graph)
            if score > best_score:
                if best_candidate:
                    rejected.append(best_candidate)
                best_score = score
                best_candidate = cand
            else:
                rejected.append(cand)
                
        return best_candidate, best_score, rejected
