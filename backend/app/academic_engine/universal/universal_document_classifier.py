import re

def classify_document_universally(full_text: str) -> dict:
    """
    Universal document classifier using keywords, structure, and language density.
    """
    text = full_text.upper()
    
    classification = {
        "document_category": "unknown",
        "document_type": "unknown",
        "subtype": "unknown",
        "level": "unknown",
        "board_university": None,
        "confidence": 0.0,
        "level_confidence": 0.0,
        "subtype_confidence": 0.0
    }
    
    if "SECONDARY SCHOOL CERTIFICATE" in text or "SSC" in text:
        classification["document_category"] = "ssc_marksheet"
        classification["document_type"] = "ssc"
        classification["subtype"] = "ssc_certificate" if "CERTIFICATE" in text else "ssc_marksheet"
        classification["level"] = "SSC"
        classification["confidence"] = 0.9
        classification["subtype_confidence"] = 0.9
        classification["level_confidence"] = 0.9
    elif "HIGHER SECONDARY CERTIFICATE" in text or "HSC" in text:
        classification["document_category"] = "hsc_marksheet"
        classification["document_type"] = "hsc"
        classification["subtype"] = "hsc_certificate" if "CERTIFICATE" in text else "hsc_marksheet"
        classification["level"] = "HSC"
        classification["confidence"] = 0.9
        classification["subtype_confidence"] = 0.9
        classification["level_confidence"] = 0.9
    elif any(k in text for k in ["DEGREE", "UNIVERSITY", "BACHELOR", "MASTER", "STATEMENT OF MARKS", "GRADE CARD"]):
        classification["document_category"] = "degree_marksheet"
        classification["document_type"] = "degree"
        classification["subtype"] = "grade_card" if "GRADE" in text else "degree_marksheet"
        classification["level"] = "DEGREE"
        classification["confidence"] = 0.85
        classification["subtype_confidence"] = 0.85
        classification["level_confidence"] = 0.85
        
    return classification
