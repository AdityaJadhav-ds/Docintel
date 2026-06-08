"""
academic_engine/extractors/academic_name_extractor.py
=======================================================
Production-grade Universal Name Extraction for Indian Academic Documents.

Supports: Maharashtra Board (SSC/HSC), CBSE, ICSE, State Boards,
          Autonomous Colleges, Universities, Diploma Boards.

Pipeline:
  1. Normalize OCR text
  2. Label detection (fuzzy, multi-language)
  3. Bbox-aware nearby-text extraction
  4. Multi-candidate scoring
  5. Garbage filter
  6. Fallback heuristics (top-region scan, ALL-CAPS scan)
  7. Confidence gating — never return low-confidence garbage

Output:
  {
    "name": str | None,
    "confidence": float,          # 0.0 – 1.0
    "method": str,                # which strategy succeeded
    "debug": { ... }             # label hits, candidates, scores
  }

DO NOT import this from KYC / Aadhaar / PAN flows.
"""

from __future__ import annotations

import re
import logging
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Minimum confidence to emit a name (below this → return None)
_MIN_CONFIDENCE = 0.45

# Name field labels — English, Marathi, Hindi variants
_NAME_LABELS: List[str] = [
    # English
    "candidate name", "candidates name", "name of candidate",
    "student name", "students name", "name of student",
    "examinee name", "name of examinee",
    "scholar name", "name of scholar",
    "applicant name", "full name",
    "name", "naam",
    # Short combined forms
    "seat no name", "roll no name",
    # Marathi (transliterated & unicode)
    "vidhyarthyache nav", "vidhyarthyache naav",
    "pariksharthyache nav",
    "ummedvaraache nav",
    # Unicode Marathi
    "विद्यार्थ्याचे नाव", "परीक्षार्थ्याचे नाव",
    "उमेदवाराचे नाव", "नाव",
    # Hindi
    "छात्र का नाम", "अभ्यर्थी का नाम", "परीक्षार्थी का नाम",
    "नाम",
]

# Certificate/degree anchor phrases
_CERT_ANCHORS: List[str] = [
    "this is to certify that",
    "certified that",
    "is to certify",
    "awarded to",
    "conferred upon",
    "conferred to",
    "degree is awarded to",
    "this certifies that",
    "certify that mr", "certify that ms", "certify that mrs",
    "certify that shri", "certify that smt",
    "has successfully completed",
    "has passed",
    "has been awarded",
]

# Hard-reject words — anything containing these is NOT a name
_REJECT_WORDS: set = {
    # Subjects
    "english", "physics", "chemistry", "biology", "mathematics", "maths",
    "geography", "science", "history", "civics", "economics", "computer",
    "marathi", "hindi", "sanskrit", "french", "german", "urdu", "gujarati",
    "drawing", "arts", "commerce", "technology", "information", "social",
    "environment", "health", "physical", "education", "defence", "vocational",
    "algebra", "geometry", "calculus", "statistics", "accounts", "accounting",
    "sociology", "psychology", "philosophy", "literature", "engineering",
    # Academic meta
    "semester", "grade", "percentage", "board", "university", "result",
    "total", "marks", "obtained", "statement", "secondary", "higher",
    "primary", "certificate", "examination", "district", "division",
    "principal", "secretary", "chairman", "controller", "registrar",
    "maharashtra", "cbse", "icse", "msbshse", "aggregate", "maximum",
    "minimum", "scores", "records", "subjects", "college", "institute",
    "school", "vidyalaya", "vidyapeeth", "department", "ministry",
    # Table headers
    "theory", "practical", "internal", "external", "written", "oral",
    "project", "assessment", "viva", "lab", "workshop",
    "subject", "code", "obtained", "maximum", "grand", "total",
    # Noise
    "null", "none", "na", "n/a", "not", "available",
}

# Pattern: lines that look like table rows (reject)
_TABLE_ROW_RE = re.compile(
    r"\b(?:marks?|obtained|maximum|theory|practical|subject|code|total|"
    r"internal|external|written|oral|figure|percentage|aggregate|sr\.?\s*no)\b",
    re.IGNORECASE,
)

# Pattern: lines containing numeric-heavy content (reject as name)
_NUMERIC_HEAVY_RE = re.compile(r"\d{2,}")

# Pattern: valid name characters
_NAME_CHARS_RE = re.compile(r"^[A-Za-z\u0900-\u097F\s\.\-\']+$")

# Pattern: institution line detector
_INSTITUTION_RE = re.compile(
    r"\b(?:board|university|college|institute|school|vidyalaya|vidyapeeth|"
    r"government|govt|department|ministry|council|bureau|authority|trust|"
    r"society|foundation|academy|center|centre)\b",
    re.IGNORECASE,
)

# OCR garbage characters
_GARBAGE_CHARS_RE = re.compile(r"[{}()\[\]|:;_=+~`<>@#^*\\/\!\$\&\*\^]")


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NameCandidate:
    text: str
    score: float = 0.0
    method: str = "unknown"
    label_hit: str = ""
    debug_notes: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    name: Optional[str]
    confidence: float
    method: str
    debug: Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — TEXT NORMALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_text(raw: str) -> str:
    """Strip control chars, collapse whitespace, keep Marathi/Hindi Unicode."""
    if not raw:
        return ""
    # Remove non-printable (keep tab, newline, Devanagari U+0900–U+097F)
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u0900-\u097F]", " ", raw)
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t]{2,}", " ", ln).strip()
        if re.search(r"[A-Za-z0-9\u0900-\u097F]", ln):
            lines.append(ln)
    return "\n".join(lines)


def _clean_candidate(raw: str) -> str:
    """Clean a raw name candidate string."""
    s = _GARBAGE_CHARS_RE.sub(" ", raw)
    s = re.sub(r"\s{2,}", " ", s)
    s = s.strip(" .,/-")
    return s.strip()


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — FUZZY LABEL MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_label_match(line_lower: str, labels: List[str]) -> Tuple[bool, str, float]:
    """
    Check if line_lower contains any of the known name labels.
    Returns (matched, label_hit, score).
    Uses substring + token overlap (no heavy deps).
    """
    for label in labels:
        label_l = label.lower()
        # Exact substring
        if label_l in line_lower:
            return True, label, 1.0
        # Token overlap ≥ 60%
        label_tokens = set(label_l.split())
        line_tokens  = set(line_lower.split())
        if label_tokens and len(label_tokens & line_tokens) / len(label_tokens) >= 0.6:
            return True, label, 0.8
    return False, "", 0.0


def _is_cert_anchor(line_lower: str) -> Tuple[bool, str]:
    """Detect certificate 'this is to certify that...' patterns."""
    for anchor in _CERT_ANCHORS:
        if anchor in line_lower:
            return True, anchor
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — NAME VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _is_valid_name(s: str) -> Tuple[bool, str]:
    """
    Validate that s looks like a real human name.
    Returns (valid, rejection_reason).
    """
    s = s.strip()
    if not s:
        return False, "empty"
    if len(s) < 3 or len(s) > 80:
        return False, f"length {len(s)} out of range"

    words = s.split()
    if len(words) < 2 or len(words) > 7:
        return False, f"word count {len(words)} invalid"

    low_words = {w.lower().rstrip(".") for w in words}

    # Reject known garbage words
    if low_words & _REJECT_WORDS:
        bad = low_words & _REJECT_WORDS
        return False, f"reject words: {bad}"

    # Reject table-like lines
    if _TABLE_ROW_RE.search(s):
        return False, "table row pattern"

    # Reject institution lines
    if _INSTITUTION_RE.search(s):
        return False, "institution pattern"

    # Reject numeric-heavy
    if _NUMERIC_HEAVY_RE.search(s):
        return False, "contains numbers"

    # Must be ≥ 80% alphabetic + space characters
    alpha_space = sum(c.isalpha() or c.isspace() for c in s)
    if alpha_space / len(s) < 0.80:
        return False, f"alpha ratio {alpha_space/len(s):.2f} too low"

    # Must pass character class check
    if not _NAME_CHARS_RE.match(s):
        return False, "invalid characters"

    return True, "ok"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — CANDIDATE SCORING
# ─────────────────────────────────────────────────────────────────────────────

def _score_candidate(cand: str, method: str, label_score: float = 0.5) -> float:
    """
    Score a candidate name string on 0–1 scale.
    Higher = more likely a real name.
    """
    score = 0.0
    words = cand.split()
    n = len(words)

    # Word count bonus (2-4 words ideal)
    if 2 <= n <= 4:
        score += 0.30
    elif n == 5:
        score += 0.15
    else:
        score += 0.05

    # Label proximity bonus
    score += label_score * 0.25

    # Proper capitalization (Title Case or ALL CAPS)
    titled = sum(1 for w in words if w and w[0].isupper())
    if titled == n:
        score += 0.20   # all words capitalized
    elif titled >= n // 2:
        score += 0.10

    # Length bonus (sweet spot 8–30 chars)
    clen = len(cand)
    if 6 <= clen <= 35:
        score += 0.15
    elif clen <= 5 or clen > 50:
        score -= 0.10

    # Method bonus
    method_bonuses = {
        "label_right": 0.15,
        "label_below": 0.12,
        "cert_anchor":  0.12,
        "caps_scan":   0.05,
        "top_region":  0.04,
    }
    score += method_bonuses.get(method, 0.0)

    # Pure-alpha bonus (no digits at all)
    if all(c.isalpha() or c.isspace() or c in ".-'" for c in cand):
        score += 0.05

    return min(max(score, 0.0), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — LABEL-ANCHORED EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_label_anchored(lines: List[str]) -> List[NameCandidate]:
    """
    For each line containing a name label, look right of the colon/dash
    and in the next 1-5 lines for a valid name candidate.
    """
    candidates: List[NameCandidate] = []

    for i, line in enumerate(lines):
        line_lower = line.lower()
        matched, label_hit, label_score = _fuzzy_label_match(line_lower, _NAME_LABELS)
        if not matched:
            continue

        debug_notes = [f"label='{label_hit}' at line {i}"]

        # Strategy A: name is on the RIGHT side of the label (same line)
        # e.g. "Name of Student : JADHAV ADITYA"
        # Split on colon / dash / tab
        parts = re.split(r"[:\-–\t]\s*", line, maxsplit=1)
        if len(parts) == 2:
            right = _clean_candidate(parts[1])
            if right:
                valid, reason = _is_valid_name(right)
                if valid:
                    # Take first slash-separated token (bilingual docs)
                    right = re.split(r"\s*/\s*", right)[0].strip()
                    sc = _score_candidate(right, "label_right", label_score)
                    candidates.append(NameCandidate(
                        text=right, score=sc, method="label_right",
                        label_hit=label_hit,
                        debug_notes=debug_notes + [f"right_text='{right}'"],
                    ))

        # Strategy B: scan next 1–5 lines BELOW the label
        for j in range(i + 1, min(i + 6, len(lines))):
            next_line = lines[j].strip()
            if not next_line:
                continue
            # Skip if this line itself is also a label
            is_label, _, _ = _fuzzy_label_match(next_line.lower(), _NAME_LABELS)
            if is_label:
                break
            if _TABLE_ROW_RE.search(next_line):
                break

            candidate_text = _clean_candidate(next_line)
            # Take only part before "/" (bilingual line)
            candidate_text = re.split(r"\s*/\s*", candidate_text)[0].strip()
            valid, reason = _is_valid_name(candidate_text)
            if valid:
                sc = _score_candidate(candidate_text, "label_below", label_score)
                candidates.append(NameCandidate(
                    text=candidate_text, score=sc, method="label_below",
                    label_hit=label_hit,
                    debug_notes=debug_notes + [f"below_line_{j}='{candidate_text}'"],
                ))
                break  # take first valid

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — CERTIFICATE ANCHOR EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_cert_anchored(lines: List[str]) -> List[NameCandidate]:
    """
    For degree/diploma certificates: extract name after 'this is to certify that ...'
    e.g. "This is to certify that ADITYA JADHAV has successfully..."
    """
    candidates: List[NameCandidate] = []
    full_text = " ".join(lines)
    full_lower = full_text.lower()

    for anchor in _CERT_ANCHORS:
        idx = full_lower.find(anchor)
        if idx == -1:
            continue
        after = full_text[idx + len(anchor):].strip()
        # Remove salutations
        after = re.sub(r"^(?:Mr\.?|Ms\.?|Mrs\.?|Shri\.?|Smt\.?|Dr\.?)\s*", "", after, flags=re.IGNORECASE)
        # Take first 6 words
        words = after.split()[:6]
        for end in range(len(words), 1, -1):
            chunk = " ".join(words[:end])
            chunk = _clean_candidate(chunk)
            valid, _ = _is_valid_name(chunk)
            if valid:
                sc = _score_candidate(chunk, "cert_anchor", 0.9)
                candidates.append(NameCandidate(
                    text=chunk, score=sc, method="cert_anchor",
                    label_hit=anchor,
                    debug_notes=[f"cert anchor='{anchor}' → '{chunk}'"],
                ))
                break

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — FALLBACK: TOP-REGION & ALL-CAPS SCAN
# ─────────────────────────────────────────────────────────────────────────────

def _extract_fallback(lines: List[str]) -> List[NameCandidate]:
    """
    Fallback strategies when no label is found:
    A) ALL-CAPS 2-5 word sequence in top 40% of document
    B) Title-case 2-5 word sequence in top 30% of document
    C) Any valid name in full document (last resort)
    """
    candidates: List[NameCandidate] = []
    n_lines = len(lines)
    top_40 = lines[: max(1, int(n_lines * 0.40))]
    top_30 = lines[: max(1, int(n_lines * 0.30))]

    # Strategy A: ALL-CAPS in top 40%
    for i, line in enumerate(top_40):
        s = _clean_candidate(line)
        if not s:
            continue
        if _TABLE_ROW_RE.search(s):
            continue
        words = s.split()
        if len(words) < 2:
            continue
        # ALL-CAPS check
        if all(w.isupper() and w.isalpha() for w in words):
            valid, reason = _is_valid_name(s)
            if valid:
                # Slightly lower score — no label context
                sc = _score_candidate(s, "caps_scan", 0.3)
                # Boost if in very top lines
                if i < n_lines * 0.15:
                    sc += 0.05
                candidates.append(NameCandidate(
                    text=s, score=sc, method="caps_scan",
                    debug_notes=[f"ALL-CAPS at line {i}: '{s}'"],
                ))

    # Strategy B: Title Case in top 30%
    for i, line in enumerate(top_30):
        s = _clean_candidate(line)
        if not s:
            continue
        if _TABLE_ROW_RE.search(s):
            continue
        words = s.split()
        if len(words) < 2:
            continue
        titled = sum(1 for w in words if w and w[0].isupper() and w[1:].islower())
        if titled >= max(2, len(words) - 1):
            valid, _ = _is_valid_name(s)
            if valid:
                sc = _score_candidate(s, "top_region", 0.3)
                candidates.append(NameCandidate(
                    text=s, score=sc, method="top_region",
                    debug_notes=[f"Title-case at line {i}: '{s}'"],
                ))

    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — FORMAT WINNER
# ─────────────────────────────────────────────────────────────────────────────

def _format_name(raw: str) -> str:
    """
    Normalize final name output:
    - ALL-CAPS → preserve (old SSC marksheets)
    - mixed-case → .title()
    - strip noise
    """
    s = raw.strip()
    if not s:
        return s
    # If ALL-CAPS — preserve formatting (authentic SSC/CBSE style)
    words = s.split()
    if all(w.isupper() for w in words if w.isalpha()):
        return s
    # Title-case if lower or mixed
    return s.title()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def extract_academic_name(
    ocr_text: str,
    zone_texts: Optional[Dict[str, str]] = None,
    doc_subtype: str = "marksheet",
) -> ExtractionResult:
    """
    Universal academic name extractor.

    Args:
        ocr_text:    Full OCR text from the document (any zone).
        zone_texts:  Optional dict of zone-specific texts (header, candidate, cert_stmt, summary).
                     When provided, candidate + cert_stmt zones are searched first.
        doc_subtype: 'marksheet' | 'certificate' | 'transcript'

    Returns:
        ExtractionResult with name, confidence, method, debug info.
    """
    debug: Dict[str, Any] = {
        "label_hits": [],
        "candidates": [],
        "winner": None,
        "rejection_reason": None,
    }

    # ── Build search corpus ──────────────────────────────────────────────────
    # Priority: candidate zone → cert_stmt zone → header → full text
    search_texts: List[str] = []
    if zone_texts:
        for zone in ("candidate", "cert_stmt", "header", "summary"):
            zt = zone_texts.get(zone) or ""
            if zt.strip():
                search_texts.append(zt)
    search_texts.append(ocr_text or "")

    # Deduplicate and normalize
    combined_raw = "\n".join(search_texts)
    normalized   = _normalize_text(combined_raw)
    lines        = [ln.strip() for ln in normalized.splitlines() if ln.strip()]

    if not lines:
        debug["rejection_reason"] = "no text"
        logger.warning("[name_extractor] No text to process")
        return ExtractionResult(name=None, confidence=0.0, method="no_text", debug=debug)

    all_candidates: List[NameCandidate] = []

    # ── Step 5: Label-anchored extraction ────────────────────────────────────
    label_candidates = _extract_label_anchored(lines)
    all_candidates.extend(label_candidates)
    debug["label_hits"] = [c.label_hit for c in label_candidates]

    # ── Step 6: Certificate anchor extraction ────────────────────────────────
    if doc_subtype in ("certificate", "degree", "diploma") or not label_candidates:
        cert_candidates = _extract_cert_anchored(lines)
        all_candidates.extend(cert_candidates)

    # ── Step 7: Fallback ─────────────────────────────────────────────────────
    if not all_candidates:
        fallback_candidates = _extract_fallback(lines)
        all_candidates.extend(fallback_candidates)
    elif max(c.score for c in all_candidates) < 0.50:
        # Supplement with fallback if existing candidates are weak
        fallback_candidates = _extract_fallback(lines)
        all_candidates.extend(fallback_candidates)

    # ── Log all candidates ───────────────────────────────────────────────────
    debug["candidates"] = [
        {"text": c.text, "score": round(c.score, 3), "method": c.method,
         "label": c.label_hit, "notes": c.debug_notes}
        for c in all_candidates
    ]

    logger.debug(
        "[name_extractor] %d candidates found: %s",
        len(all_candidates),
        [(c.text, round(c.score, 3), c.method) for c in all_candidates[:5]],
    )

    if not all_candidates:
        debug["rejection_reason"] = "no valid candidates"
        logger.info("[name_extractor] No valid name candidates found")
        return ExtractionResult(name=None, confidence=0.0, method="no_candidates", debug=debug)

    # ── Pick winner ──────────────────────────────────────────────────────────
    winner = max(all_candidates, key=lambda c: c.score)
    debug["winner"] = {"text": winner.text, "score": round(winner.score, 3), "method": winner.method}

    logger.info(
        "[name_extractor] Winner: '%s' (score=%.3f, method=%s)",
        winner.text, winner.score, winner.method,
    )

    # ── Confidence gate ──────────────────────────────────────────────────────
    if winner.score < _MIN_CONFIDENCE:
        debug["rejection_reason"] = f"winner score {winner.score:.3f} below threshold {_MIN_CONFIDENCE}"
        logger.info(
            "[name_extractor] Rejected '%s' — score %.3f < %.2f",
            winner.text, winner.score, _MIN_CONFIDENCE,
        )
        return ExtractionResult(name=None, confidence=winner.score, method="low_confidence", debug=debug)

    final_name = _format_name(winner.text)
    return ExtractionResult(
        name=final_name,
        confidence=round(winner.score, 3),
        method=winner.method,
        debug=debug,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE WRAPPER  (drop-in for field_extractors call sites)
# ─────────────────────────────────────────────────────────────────────────────

def extract_candidate_name_universal(
    zone_texts: Dict[str, str],
    doc_subtype: str = "marksheet",
) -> Optional[str]:
    """
    Drop-in replacement for the old extract_candidate_name().
    Returns the name string or None.
    """
    full_text = "\n".join(v for v in zone_texts.values() if v)
    result = extract_academic_name(
        ocr_text=full_text,
        zone_texts=zone_texts,
        doc_subtype=doc_subtype,
    )
    return result.name
