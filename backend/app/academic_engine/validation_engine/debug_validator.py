class DebugValidator:
    """Step 10: Failure Explainer"""
    
    def __init__(self):
        self.logs = {}
        
    def log_field(self, field_name: str, original_val: str, error: str, retries: int, final_val: str, conf: float):
        self.logs[field_name] = {
            "original_value": original_val,
            "validation_error": error,
            "retries_attempted": retries,
            "repaired_final_value": final_val,
            "final_confidence": conf
        }
        
    def get_logs(self) -> dict:
        return self.logs
