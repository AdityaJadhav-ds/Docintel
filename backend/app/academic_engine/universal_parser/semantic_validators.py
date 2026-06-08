import re

def is_valid_percentage(text: str) -> bool:
    # Remove all spaces and % signs
    clean = re.sub(r'[\s%]', '', text)
    try:
        val = float(clean)
        return 0 <= val <= 100
    except ValueError:
        return False

def clean_percentage(text: str) -> str:
    # Advanced percentage resolution (Step 6)
    # If 7517 -> 75.17, 8240 -> 82.40
    clean = re.sub(r'[^\d.]', '', text)
    if not clean:
        return ""
        
    try:
        val = float(clean)
        if 0 <= val <= 100:
            return f"{val:.2f}"
            
        # Try to fix missing decimal (e.g., 7517 -> 75.17)
        if 1000 <= val <= 10000:
            fixed = val / 100
            if 0 <= fixed <= 100:
                return f"{fixed:.2f}"
                
    except ValueError:
        pass
        
    return ""

def is_valid_cgpa(text: str) -> bool:
    clean = re.sub(r'[^\d.]', '', text)
    try:
        val = float(clean)
        return 0.0 <= val <= 10.0
    except ValueError:
        return False

def is_valid_name(text: str) -> bool:
    if len(text) < 4:
        return False
    if sum(c.isalpha() for c in text) / len(text) < 0.6:
        return False
    # Reject common labels
    text_lower = text.lower()
    rejects = ["board", "university", "certificate", "marksheet", "statement", "school", "college"]
    if any(r in text_lower for r in rejects):
        return False
    return True
