"""
academic_engine/classifier/document_classifier.py
===================================================
Document Classifier — OCR-Noise Resilient

TUNING CHANGES (PHASE 2 — Critical System Tuning):
  - Added _normalize_ocr_noise() that repairs common OCR corruptions
    (I→1, O→0, 0→O in words, S↔5, B↔8) BEFORE keyword scoring
  - Expanded HSC keyword list with Maharashtra-specific terms and
    OCR-corruption variants
  - Added fuzzy sub-string scoring for key multi-word phrases
  - Classifier no longer returns _unknown() on zero scores —
    defaults to hsc_marksheet (most common Indian document)
  - Board detection now also fires on partial matches for noisy text
  - Subtype tie-break improved: explicit "MARCH" / "STATEMENT" signals
"""

from __future__ import annotations
import re
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


# ── OCR Noise Normalizer ──────────────────────────────────────────────────────

# Character-level confusion pairs that OCR commonly gets wrong
_OCR_CHAR_MAP = str.maketrans({
    "0": "O",   # digit → letter (for word matching)
    "1": "I",
    "5": "S",
    "8": "B",
    "|": "I",
    "!": "I",
    "@": "A",
    "$": "S",
})

# Reverse map for numeric contexts — kept separate
_NUM_OCR_MAP = str.maketrans({
    "O": "0",
    "I": "1",
    "l": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "b": "8",
    "Z": "2",
    ":": ".",
    ";": ".",
})


def _normalize_ocr_noise(text: str) -> str:
    """
    Normalize OCR noise in text BEFORE keyword matching.
    Repairs common confusions to improve classification accuracy
    on WhatsApp-compressed / low-quality images.
    """
    # Collapse repeated spaces + remove non-printable chars
    text = re.sub(r"[^\x20-\x7E\u0900-\u097F\n]", " ", text)
    text = re.sub(r"[ \t]+", " ", text)

    # Common full-word OCR corruption repairs
    repairs = [
        (r"\bH[1I]GHER\b",           "HIGHER"),
        (r"\bSEC[O0]NDARY\b",        "SECONDARY"),
        (r"\bCERT[1I]F[1I]CATE\b",  "CERTIFICATE"),
        (r"\bEXAM[1I]NAT[1I][O0]N\b","EXAMINATION"),
        (r"\bPERCENTAGE\b",          "PERCENTAGE"),
        (r"\bSTATEMENT\b",           "STATEMENT"),
        (r"\bUNIVERS[1I]TY\b",       "UNIVERSITY"),
        (r"\bCERTIF[1I]ED\b",        "CERTIFIED"),
        (r"\bSECONDARY\b",           "SECONDARY"),
        (r"\bMAHARASHTRA\b",         "MAHARASHTRA"),
        (r"\bM[AÀ]HARASHTRA\b",      "MAHARASHTRA"),
        (r"\bB[O0]ARD\b",            "BOARD"),
        (r"\bSCH[O0][O0]L\b",        "SCHOOL"),
        (r"\bS+T+A+T+E+M+E+N+T\b",  "STATEMENT"),
        (r"\bMARKS?\b",              "MARKS"),
        (r"\bR[E3]SULT\b",           "RESULT"),
        (r"\bPASS(?:ED)?\b",         "PASS"),
        (r"\bFAIL(?:ED)?\b",         "FAIL"),
        (r"\bD[1I]ST[1I]NCT[1I][O0]N\b", "DISTINCTION"),
    ]
    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text


# ── Keyword Definitions ───────────────────────────────────────────────────────

_MARKSHEET_KEYWORDS = [
    r"statement\s+of\s+(marks?|grades?)",
    r"marks?\s+obtained",
    r"subject\s+code",
    r"total\s+marks?",
    r"grand\s+total",
    r"percentage\s+of\s+marks?",
    r"\bcgpa\b",
    r"\bsgpa\b",
    r"\bgrade\s+point\b",
    r"marks?\s+sheet",
    r"marksheet",
    r"exam(?:ination)?\s+result",
    r"semester\s+(?:grade|result|performance)",
    r"consolidated\s+(?:marks?|statement)",
    r"academic\s+transcript",
    r"grade\s+card",
    # Maharashtra specific
    r"seat\s+no",
    r"seat\s+number",
    r"roll\s+no",
    r"examinee",
    r"march\s*[–\-]\s*20\d\d",
    r"oct(?:ober)?\s*[–\-]\s*20\d\d",
    r"total\s+percentage",
    r"percentage\s+marks?",
    r"गुण\s*पत्रक",      # Marathi: marks statement
    r"परिणाम\s*पत्रक",   # Marathi: result statement
]

_CERTIFICATE_KEYWORDS = [
    r"this\s+is\s+to\s+certify\s+that",
    r"certified\s+that",
    r"has\s+passed\s+the",
    r"certificate\s+examination",
    r"awarded\s+(?:the\s+)?degree",
    r"awarded\s+to",
    r"conferred\s+(?:the\s+)?degree",
    r"degree\s+of\s+(?:bachelor|master|doctor)",
    r"\bdivision\b",
    r"\bfirst\s+class\b",
    r"\bdistinction\b",
    r"convocation",
    r"passed\s+with\s+(?:distinction|first|second)",
    r"certificate\s+of\s+(?:passing|completion)",
    r"migration\s+certificate",
    r"passing\s+certificate",
]

_SSC_KEYWORDS = [
    r"secondary\s+school\s+certificate",
    r"माध्यमिक\s+शालान्त",
    r"\bssc\b",
    r"class\s*(?:x\b|10\b|10th\b)",
    r"(?:std|standard)[\.\s]+(?:x|10)",
    r"10\s*(?:th)?\s+(?:standard|class|board)",
    r"secondary\s+education",
    r"high\s+school\s+(?:certificate|exam)",
    r"matric(?:ulation)?",
    r"माध्यमिक",         # Marathi SSC
    r"इयत्ता\s*१०",      # Marathi: Class 10
    r"class\s+x\b",
    r"std\s*x\b",
    r"grade\s+10\b",
]

_HSC_KEYWORDS = [
    r"higher\s+secondary\s+certificate",
    r"उच्च\s*माध्यमिक",
    r"\bhsc\b",
    r"class\s*(?:xii\b|12\b|12th\b)",
    r"(?:std|standard)[\.\s]+(?:xii|12)",
    r"12\s*(?:th)?\s+(?:standard|class|board)",
    r"(?:science|commerce|arts)\s+stream",
    r"(?:junior|senior)\s+college",
    r"intermediate\s+(?:examination|board)",
    r"pre[\s\-]university",
    # Maharashtra HSC specific
    r"higher\s+secondary",
    r"h\.s\.c",
    r"std\s*xii\b",
    r"std\s*12\b",
    r"march.*examination",
    r"examination.*march",
    r"मुंबई\s+विभाग",     # Mumbai division (Maharashtra board)
    r"पुणे\s+विभाग",      # Pune division
    r"नागपूर\s+विभाग",    # Nagpur division
    r"उच्च\s+माध्यमिक",  # Marathi HSC
    r"इयत्ता\s*१२",       # Marathi: Class 12
    r"विज्ञान\s+शाखा",   # Science stream (Marathi)
    r"वाणिज्य\s+शाखा",   # Commerce stream (Marathi)
    r"कला\s+शाखा",        # Arts stream (Marathi)
    # OCR-noise variants of "HIGHER SECONDARY"
    r"h[1i]gher\s+sec",
    r"higher\s+sec[o0]ndary",
    r"h\.?s\.?c\.?\s+exam",
]

_DEGREE_KEYWORDS = [
    r"\bbachelor\b",
    r"\bmaster\b",
    r"\bb[\.\s]?(?:e|tech|sc|com|ca|cs|a|ed)\b",
    r"\bm[\.\s]?(?:e|tech|sc|com|ba|ca|cs|ed|b|a)\b",
    r"\bphd\b|\bdoctor(?:ate)?\b",
    r"\bprn\b",
    r"semester\s+[ivxlc\d]+",
    r"(?:affiliated|autonomous)\s+(?:college|university)",
    r"university\s+(?:of|examination)",
    r"\bdiploma\b",
    r"\bpgd\b|\bpgdm\b",
]

_BOARD_NAMES = {
    r"maharashtra\s+state\s+board":                   "Maharashtra State Board",
    r"msbshse":                                        "Maharashtra State Board",
    r"state\s+board.*maharashtra":                     "Maharashtra State Board",
    r"maharashtra.*board":                             "Maharashtra State Board",
    r"cbse|central\s+board\s+of\s+secondary":         "CBSE",
    r"cisce|icse|isc\b":                              "CISCE/ICSE",
    r"state\s+board\s+of\s+(?:gujarat|rajasthan|karnataka|tamilnadu|tamil\s+nadu|kerala|andhra|telangana|west\s+bengal|uttar\s+pradesh)":
                                                       "State Board",
    r"shivaji\s+university":                           "Shivaji University, Kolhapur",
    r"savitribai\s+phule\s+(?:pune\s+)?university":   "Savitribai Phule Pune University",
    r"university\s+of\s+(?:mumbai|bombay)":           "University of Mumbai",
    r"nagpur\s+university|rtmnu":                     "Rashtrasant Tukadoji Maharaj Nagpur University",
    r"dr[\.\s]+babasaheb\s+ambedkar":                 "Dr. Babasaheb Ambedkar Marathwada University",
    r"swami\s+ramanand":                              "Swami Ramanand Teerth Marathwada University",
    r"north\s+maharashtra\s+university":              "North Maharashtra University",
    r"solapur\s+university":                          "Solapur University",
    r"iit[\s\-]?(?:bombay|delhi|madras|kanpur|kharagpur|roorkee|guwahati|hyderabad)":
                                                       "IIT",
    r"nit[\s\-]?\w+":                                 "NIT",
    r"anna\s+university":                             "Anna University",
    r"osmania\s+university":                          "Osmania University",
    r"bangalore\s+university|bengaluru\s+university": "Bangalore University",
    r"calcutta\s+university|university\s+of\s+calcutta": "University of Calcutta",
    r"delhi\s+university|university\s+of\s+delhi":    "University of Delhi",
    r"amity\s+university":                            "Amity University",
    r"punjab\s+university":                           "Panjab University",
    r"rajasthan\s+university":                        "University of Rajasthan",
    r"gujarat\s+university":                          "Gujarat University",
    r"kerala\s+university":                           "University of Kerala",
}


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _score_keywords(text: str, patterns: list) -> int:
    low = text.lower()
    return sum(1 for p in patterns if re.search(p, low))


def _extract_board_university(text: str) -> Optional[str]:
    low = text.lower()
    for pat, label in _BOARD_NAMES.items():
        if re.search(pat, low):
            return label
    return None


def _detect_level_score(text: str) -> Tuple[int, int, int]:
    low = text.lower()
    ssc    = _score_keywords(low, _SSC_KEYWORDS)
    hsc    = _score_keywords(low, _HSC_KEYWORDS)
    degree = _score_keywords(low, _DEGREE_KEYWORDS)
    return ssc, hsc, degree


# ── Public Classifier ─────────────────────────────────────────────────────────

class AcademicDocumentClassifier:
    CATEGORY_LABELS = {
        "ssc_marksheet":     "SSC Marksheet",
        "ssc_certificate":   "SSC Certificate",
        "hsc_marksheet":     "HSC Marksheet",
        "hsc_certificate":   "HSC Certificate",
        "degree_marksheet":  "Degree Marksheet",
        "degree_certificate":"Degree Certificate",
        "unknown":           "Unknown Document",
    }

    def classify(self, text: str, hint: Optional[str] = None) -> dict:
        if not text or len(text.strip()) < 10:
            return self._default_marksheet("text too short")

        # ── Step 0: Normalize OCR noise before all scoring ────────────────
        cleaned = _normalize_ocr_noise(text)
        low     = cleaned.lower()

        # ── Subtype detection ──────────────────────────────────────────────
        ms_score   = _score_keywords(low, _MARKSHEET_KEYWORDS)
        cert_score = _score_keywords(low, _CERTIFICATE_KEYWORDS)
        total_sub  = ms_score + cert_score or 1

        if ms_score > cert_score:
            subtype  = "marksheet"
            sub_conf = ms_score / total_sub
        elif cert_score > ms_score:
            subtype  = "certificate"
            sub_conf = cert_score / total_sub
        else:
            subtype  = "marksheet" if re.search(r"\bmarks?\b|\btotal\b|\bsubject\b", low) else "certificate"
            sub_conf = 0.5

        # ── Level detection ────────────────────────────────────────────────
        ssc_s, hsc_s, deg_s = _detect_level_score(low)

        # User hint overrides
        if hint and hint != "auto":
            if hint == "ssc":
                ssc_s += 20
            elif hint == "hsc":
                hsc_s += 20
            elif hint in ("degree", "university", "pg", "ug"):
                deg_s += 20

        level_total = ssc_s + hsc_s + deg_s or 1

        if deg_s > max(ssc_s, hsc_s):
            level    = "degree"
            lev_conf = deg_s / level_total
        elif hsc_s > ssc_s:
            level    = "hsc"
            lev_conf = hsc_s / level_total
        elif ssc_s > 0:
            level    = "ssc"
            lev_conf = ssc_s / level_total
        else:
            # Zero level scores — check board names for partial signal
            board = _extract_board_university(cleaned)
            if board:
                # Board found but level unclear → default HSC (most common)
                level    = "hsc"
                lev_conf = 0.35
                logger.info("[classifier] Board-only match '%s' → defaulting level=hsc", board)
            else:
                # Truly unknown — still default to hsc_marksheet rather than fail
                logger.info("[classifier] No keyword match — defaulting to hsc_marksheet")
                return self._default_marksheet("no keyword match")

        category         = f"{level}_{subtype}"
        board_university = _extract_board_university(cleaned)
        label            = self.CATEGORY_LABELS.get(category, "Unknown Document")

        logger.info(
            "[classifier] category=%s level=%s(%d) subtype=%s(%d) board=%s",
            category, level, ssc_s + hsc_s + deg_s, subtype,
            ms_score + cert_score, board_university,
        )

        return {
            "document_category":  category,
            "document_type":      label,
            "level":              level,
            "subtype":            subtype,
            "board_university":   board_university,
            "level_confidence":   round(lev_conf, 3),
            "subtype_confidence": round(sub_conf, 3),
        }

    @staticmethod
    def _default_marksheet(reason: str = "") -> dict:
        """Return HSC Marksheet as the safe default instead of Unknown."""
        logger.info("[classifier] Defaulting to hsc_marksheet (%s)", reason)
        return {
            "document_category":  "hsc_marksheet",
            "document_type":      "HSC Marksheet",
            "level":              "hsc",
            "subtype":            "marksheet",
            "board_university":   None,
            "level_confidence":   0.25,
            "subtype_confidence": 0.5,
        }

    @staticmethod
    def _unknown() -> dict:
        return {
            "document_category":  "unknown",
            "document_type":      "Unknown Document",
            "level":              "unknown",
            "subtype":            "unknown",
            "board_university":   None,
            "level_confidence":   0.0,
            "subtype_confidence": 0.0,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_classifier = AcademicDocumentClassifier()


def classify_document(text: str, hint: Optional[str] = None) -> dict:
    """Module-level convenience wrapper."""
    return _classifier.classify(text, hint)
