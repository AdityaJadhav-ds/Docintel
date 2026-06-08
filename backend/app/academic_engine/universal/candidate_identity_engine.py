import re
import logging
from typing import List

logger = logging.getLogger(__name__)

def extract_candidate_name(lines: List[List[str]], full_text: str) -> str:
    """
    Extracts the candidate name using semantic anchors and geometric proximity.
    """
    anchors = [
        "CANDIDATE NAME", "NAME OF CANDIDATE", "STUDENT NAME",
        "NAME :", "NAME:", "THIS IS TO CERTIFY THAT", "SURNAME FIRST"
    ]
    
    # Simple regex fallbacks
    for line_nodes in lines:
        line_text = " ".join([n.text for n in line_nodes]).upper()
        
        for anchor in anchors:
            if anchor in line_text:
                # The name is usually right after the anchor or on the next line
                # Removing the anchor from the text
                name_part = line_text.split(anchor)[-1].strip()
                name_part = re.sub(r'^[:\-\s]+', '', name_part)
                
                if len(name_part) > 5 and not re.search(r'\d', name_part):
                    return name_part.title()
                
    # Next, look for all uppercase text blocks that look like names
    # Heuristics:
    # 1. 2-4 words
    # 2. No numbers
    # 3. Not a known label (BOARD, UNIVERSITY, MARKS, etc.)
    exclude_words = {"BOARD", "UNIVERSITY", "EDUCATION", "SECONDARY", "HIGHER", "SCHOOL", "MARKS", "STATEMENT", "CERTIFICATE"}
    
    for line_nodes in lines:
        line_text = " ".join([n.text for n in line_nodes]).upper()
        words = line_text.split()
        
        if 2 <= len(words) <= 5 and not any(char.isdigit() for char in line_text):
            if not any(ew in words for ew in exclude_words):
                # Check if all words are 2+ chars
                if all(len(w) >= 2 for w in words):
                    return line_text.title()
                    
    return None
