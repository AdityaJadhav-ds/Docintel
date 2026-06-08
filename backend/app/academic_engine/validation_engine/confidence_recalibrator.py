class ConfidenceRecalibrator:
    """Step 6: Confidence Recalibration"""
    
    def recalibrate(self, initial_conf: float, was_repaired: bool, passed_validation: bool, retries: int) -> float:
        new_conf = initial_conf
        
        if was_repaired:
            # Repairs increase our trust that we've found a known pattern, but reduce raw text trust
            new_conf = (new_conf + 0.9) / 2.0
            
        if passed_validation:
            new_conf += 0.1
        else:
            new_conf -= 0.3
            
        if retries > 0:
            # If we had to retry, confidence is inherently slightly penalised, 
            # but if it passed validation we don't drop it too much.
            new_conf -= (0.05 * retries)
            
        return min(1.0, max(0.0, new_conf))
