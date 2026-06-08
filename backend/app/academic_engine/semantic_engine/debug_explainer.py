class DebugExplainer:
    """Step 12: Debug Explainer"""
    
    def __init__(self):
        self.logs = {}
        
    def log_field_extraction(self, field_name: str, label_used: str, all_candidates: list, rejected: list, selected: dict, conf: float):
        self.logs[field_name] = {
            "label_used": label_used,
            "candidates_found": [c['value'] for c in all_candidates],
            "rejected_candidates": [c['value'] for c in rejected],
            "final_selected": selected['value'] if selected else None,
            "confidence_score": conf
        }
        
    def get_logs(self):
        return self.logs
