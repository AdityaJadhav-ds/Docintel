from typing import List
from ..models import OCRToken

class DocumentClassifier:
    def classify(self, tokens: List[OCRToken]) -> str:
        text_corpus = " ".join([t.text.upper() for t in tokens])
        
        if "SECONDARY SCHOOL CERTIFICATE" in text_corpus and "MARKS" in text_corpus:
            return "SSC_MARKSHEET"
        if "HIGHER SECONDARY CERTIFICATE" in text_corpus and "MARKS" in text_corpus:
            return "HSC_MARKSHEET"
        if "UNIVERSITY" in text_corpus and "GRADE" in text_corpus:
            return "UNIVERSITY_GRADE_CARD"
            
        return "UNKNOWN_ACADEMIC_DOCUMENT"
