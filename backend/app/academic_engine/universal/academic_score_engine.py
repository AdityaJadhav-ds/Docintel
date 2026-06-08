import re
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def extract_academic_scores(lines: List[List['SpatialNode']]) -> Dict[str, Any]:
    """
    Universally extracts Percentage, CGPA, SGPA, SPI, etc. using semantic proximity
    and rejects subject marks/totals/random decimals.
    """
    scores = {
        "percentage": None,
        "cgpa": None,
    }
    
    # Heuristics for percentage
    percentage_anchors = [r'PERCENTAGE', r'%', r'PER\.', r'PERCENT']
    cgpa_anchors = [r'CGPA', r'SGPA', r'CPI', r'SPI', r'GRADE POINT']
    
    for i, line in enumerate(lines):
        line_text = " ".join([n.text for n in line]).upper()
        
        # 1. Percentage
        if not scores["percentage"] and any(re.search(a, line_text) for a in percentage_anchors):
            # Scan nearby lines (current and next 2)
            for sl in lines[i:i+3]:
                for n in sl:
                    # Look for XX.XX or X.XX, but restrict to 0-100
                    text_val = n.text.replace(',', '.') # common OCR error
                    if re.match(r'^(100\.00|\d{1,2}\.\d{1,2})$', text_val):
                        try:
                            val = float(text_val)
                            if 0 < val <= 100:
                                scores["percentage"] = text_val
                                break
                        except:
                            pass
                if scores["percentage"]:
                    break
        
        # 2. CGPA
        if not scores["cgpa"] and any(re.search(a, line_text) for a in cgpa_anchors):
            for sl in lines[i:i+3]:
                for n in sl:
                    text_val = n.text.replace(',', '.')
                    # Look for 10.00 or X.XX where X is usually 4 to 9
                    if re.match(r'^(10\.0{1,2}|\d{1}\.\d{1,2})$', text_val):
                        try:
                            val = float(text_val)
                            if 0 < val <= 10:
                                scores["cgpa"] = text_val
                                break
                        except:
                            pass
                if scores["cgpa"]:
                    break
                    
    # Strict fallback cleaning for 7517 -> 75.17
    # If we didn't find a decimal but found a 4 digit number near "Percentage"
    if not scores["percentage"]:
        for i, line in enumerate(lines):
            line_text = " ".join([n.text for n in line]).upper()
            if "PERCENT" in line_text or "%" in line_text:
                for sl in lines[i:i+2]:
                    for n in sl:
                        if re.match(r'^\d{4}$', n.text):
                            val = float(n.text) / 100
                            if 30 <= val <= 100:
                                scores["percentage"] = f"{val:.2f}"
                                break
                    if scores["percentage"]:
                        break
                        
    return scores
