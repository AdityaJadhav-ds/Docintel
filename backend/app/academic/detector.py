"""
app/academic/detector.py — Auto document-type classifier
=========================================================
Classifies uploaded document as SSC / HSC / Degree / Unknown using:
  1. Weighted keyword scoring
  2. Regex pattern hits
  3. Semantic layout clues
  4. Tie-breaking confidence thresholds

Returns a DetectionResult with confidence 0-100.
"""

from __future__ import annotations
import re
from typing import List, Tuple, Dict
from app.core.logger import logger


# ── Weighted keyword maps ─────────────────────────────────────────────────────
# Format: (pattern, weight, is_regex)

SSC_SIGNALS: List[Tuple[str, float, bool]] = [
    (r"\bssc\b",                             10, True),
    (r"secondary\s+school\s+certificate",    10, True),
    (r"\bclass\s+(x|10|10th)\b",             8,  True),
    (r"\b10th\b",                            6,  True),
    (r"higher\s+secondary\s+examination",    4,  True),  # negative for HSC
    (r"\bmarch[- ]\s*20\d{2}\b",             5,  True),
    (r"\bseat\s+no\b",                       3,  True),
    (r"\bschool\s+no\b",                     3,  True),
    (r"\bcertificate\s+no\b",                3,  True),
    (r"state\s+board",                       4,  True),
    (r"\bmatriculation\b",                   6,  True),
    (r"\bicse\b",                            4,  True),
    (r"\bcbse\b",                            4,  True),
    (r"total\s+marks",                       2,  True),
    (r"obtained\s+marks",                    2,  True),
    (r"division",                            2,  True),
    (r"distinction",                         2,  True),
    (r"mother'?s?\s+name",                   2,  True),
]

HSC_SIGNALS: List[Tuple[str, float, bool]] = [
    (r"\bhsc\b",                             10, True),
    (r"higher\s+secondary\s+certificate",    10, True),
    (r"\bclass\s+(xii|12|12th)\b",           8,  True),
    (r"\b12th\b",                            6,  True),
    (r"\bscience\b",                         4,  True),
    (r"\bcommerce\b",                        4,  True),
    (r"\barts\b",                            3,  True),
    (r"\bstream\b",                          4,  True),
    (r"junior\s+college",                    4,  True),
    (r"\bfyjc\b|\bsyjc\b",                   5,  True),
    (r"higher\s+secondary",                  6,  True),
    (r"\bintermediate\b",                    5,  True),
    (r"state\s+board",                       3,  True),
    (r"\bicse\b",                            3,  True),
    (r"\bcbse\b",                            3,  True),
    (r"total\s+marks",                       2,  True),
    (r"mother'?s?\s+name",                   2,  True),
]

DEGREE_SIGNALS: List[Tuple[str, float, bool]] = [
    (r"\bsgpa\b",                            10, True),
    (r"\bcgpa\b",                            10, True),
    (r"\bsemester\b",                        8,  True),
    (r"\bsem[\s\-\.]\s*[iivx\d]+\b",        8,  True),
    (r"statement\s+of\s+grades?",            10, True),
    (r"\btranscript\b",                      8,  True),
    (r"\buniversity\b",                      6,  True),
    (r"\bprn\b",                             8,  True),
    (r"\brollno\b|\broll\s+no\b",            4,  True),
    (r"\b(b\.?tech|b\.?sc|b\.?com|b\.?e\.?|b\.?a\.?|m\.?tech|m\.?sc|mba|bca|mca)\b", 8, True),
    (r"\bbachelor\b|\bmaster\b",             6,  True),
    (r"aggregate\s+(percentage|marks)",      6,  True),
    (r"credit\s+(hours?|points?)",           5,  True),
    (r"\bgrade\s+point\b",                   5,  True),
    (r"\bresult\s+class\b",                  5,  True),
    (r"consolidated\s+marksheet",            8,  True),
    (r"\btoppers?\b",                        3,  True),
    (r"first\s+class\b",                     3,  True),
    (r"distinction\s+with",                  3,  True),
]


# ── Scoring engine ────────────────────────────────────────────────────────────

def _score_signals(text: str, signals: List[Tuple[str, float, bool]]) -> Tuple[float, List[str]]:
    """Sum weighted signal hits against lowercased text."""
    lowered = text.lower()
    total   = 0.0
    hits    = []

    for pattern, weight, is_rx in signals:
        if is_rx:
            if re.search(pattern, lowered, re.IGNORECASE):
                total += weight
                hits.append(pattern.replace(r"\b", "").replace("\\s+", " ").strip()[:30])
        else:
            if pattern.lower() in lowered:
                total += weight
                hits.append(pattern[:30])

    return total, hits


# ── Hard-override patterns ────────────────────────────────────────────────────

def _has_hard_override(text: str) -> str | None:
    """
    Certain phrases are unambiguous markers — return the type immediately.
    """
    low = text.lower()
    if re.search(r"statement\s+of\s+grades?", low):          return "degree"
    if re.search(r"\bsgpa\b.*\bcgpa\b|\bcgpa\b.*\bsgpa\b", low): return "degree"
    if re.search(r"secondary\s+school\s+certificate", low):   return "ssc"
    if re.search(r"higher\s+secondary\s+certificate", low):   return "hsc"
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def detect_document_type(raw_text: str) -> Dict:
    """
    Classify raw OCR text into ssc | hsc | degree | unknown.

    Returns:
        {
          "document_type": str,
          "confidence": float,   # 0-100
          "reason": str,
          "keyword_hits": [str],
          "scores": {"ssc": float, "hsc": float, "degree": float},
        }
    """
    if not raw_text or len(raw_text.strip()) < 30:
        return {
            "document_type": "unknown", "confidence": 0.0,
            "reason": "Insufficient text for classification",
            "keyword_hits": [], "scores": {},
        }

    # Hard override — unambiguous phrases
    override = _has_hard_override(raw_text)
    if override:
        logger.info("[detector] Hard override → %s", override)
        return {
            "document_type": override,
            "confidence": 95.0,
            "reason": "Unambiguous header/title keyword detected",
            "keyword_hits": [],
            "scores": {override: 95.0},
        }

    # Weighted scoring
    ssc_score,    ssc_hits    = _score_signals(raw_text, SSC_SIGNALS)
    hsc_score,    hsc_hits    = _score_signals(raw_text, HSC_SIGNALS)
    degree_score, degree_hits = _score_signals(raw_text, DEGREE_SIGNALS)

    scores = {"ssc": ssc_score, "hsc": hsc_score, "degree": degree_score}
    max_score = max(scores.values())

    if max_score < 5:
        return {
            "document_type": "unknown", "confidence": 0.0,
            "reason": f"Score too low — max={max_score:.1f}; need ≥5",
            "keyword_hits": [], "scores": scores,
        }

    # Determine winner
    winner   = max(scores, key=lambda k: scores[k])
    hits_map = {"ssc": ssc_hits, "hsc": hsc_hits, "degree": degree_hits}
    hits     = hits_map[winner]

    # Confidence = score / (score + runner_up) * 100 if spread is meaningful
    sorted_scores = sorted(scores.values(), reverse=True)
    top, second   = sorted_scores[0], sorted_scores[1] if len(sorted_scores) > 1 else 0
    if top == 0:
        confidence = 0.0
    else:
        spread     = (top - second) / top
        confidence = min(30 + spread * 70, 99.0)  # 30-99 range

    reason = (
        f"{winner.upper()} score={top:.1f}, next={second:.1f}, "
        f"spread={spread*100:.0f}%, hits={len(hits)}"
    )

    logger.info(
        "[detector] type=%s conf=%.1f ssc=%.1f hsc=%.1f degree=%.1f",
        winner, confidence, ssc_score, hsc_score, degree_score,
    )

    return {
        "document_type": winner,
        "confidence":    round(confidence, 1),
        "reason":        reason,
        "keyword_hits":  hits[:10],
        "scores":        scores,
    }
