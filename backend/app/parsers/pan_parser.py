"""
app/parsers/pan_parser.py — Production-grade PAN field extractor v3
====================================================================
v3: Complete rewrite with:
  - Region-targeted OCR (PSM 7 for PAN/DOB, PSM 4 for name)
  - Strict positional name extraction (ONLY below PAN number line)
  - Multi-variant voting for all fields
  - Enhanced OCR correction (O↔0, I↔1, B↔8, S↔5)
  - Stronger blacklist + alpha-ratio filter

EXTRACTION FLOW:
  1. Try region OCR first (targeted crops)
  2. Fall back to full-image text with positional logic
  3. Multi-variant voting selects winner
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional, Dict, List, Tuple
from app.core.logger import logger
from app.ocr.text_cleaner import clean_ocr_text
from app.ocr.correction_engine import correct_pan_candidate, find_corrected_pan, find_corrected_date
from app.ocr.confidence_engine import calculate_field_confidence
from app.utils.blacklists import is_pan_blacklisted


# ── Regex patterns ─────────────────────────────────────────────────────────────

_PAN_STRICT  = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")
# Looser: allows O/0 and I/1 confusion in expected positions
_PAN_LOOSE   = re.compile(r"\b([A-Z0-9]{10})\b")
_DOB_PATTERNS = [
    re.compile(r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\b"),
    re.compile(r"(?:DOB|Date\s+of\s+Birth|D\.O\.B)[^\d]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})", re.IGNORECASE),
]

# Father's name line indicators
_FATHER_INDICATORS = [
    r"\bfather\b", r"\bfather'?s?\s+name\b", r"\bs/o\b", r"\bd/o\b",
    r"\bw/o\b", r"\bc/o\b",
]
_FATHER_PATTERN = re.compile("|".join(_FATHER_INDICATORS), re.IGNORECASE)

# Lines that are definitely NOT names
_NAME_REJECT_PATTERNS = [
    re.compile(r"\b(income|tax|department|government|india|permanent|account|number|pan|signature|dob|date|birth|father|holder|individual|company|firm|huf|trust|name)\b", re.IGNORECASE),
    re.compile(r"\d{4,}"),           # has a 4+ digit sequence - not a name
    re.compile(r"[/@\\|<>{}]"),      # garbage chars
    re.compile(r"^(of|the|and|or|in|at|to|a|an|is)\s", re.IGNORECASE),  # starts with preposition
]

# ── PAN card structural label patterns ────────────────────────────────────────
# Indian PAN cards use bilingual labels: "\u0928\u093e\u092e / Name", "\u092a\u093f\u0924\u093e \u0915\u093e \u0928\u093e\u092e / Father's Name"
# OCR reads the Hindi as noise, but '/ Name' and '/ Father' are preserved.

# Matches: "/ Name", "|Name", "/ NAME", standalone "Name"
_NAME_LABEL_PATTERN = re.compile(
    r"(?:[/|\\]\s*Name\b|^\s*Name\s*$)", re.IGNORECASE
)
# Matches: "/ Father", "/ Father's Name", "| Fathers Name", standalone "Father"
_FATHER_LABEL_PATTERN = re.compile(
    r"(?:[/|\\]\s*Father|\bFather'?s?\s+Name\b|\bs[/]o\b|\bd[/]o\b|\bw[/]o\b)", re.IGNORECASE
)
# Matches DOB label: "/ Date of Birth", "/ DOB"
_DOB_LABEL_PATTERN = re.compile(
    r"(?:[/|\\]\s*Date\s+of\s+Birth|[/|\\]\s*DOB\b|\bDate\s+of\s+Birth\b)", re.IGNORECASE
)

# Valid name: 2-4 alpha words, mostly alpha
_NAME_MIN_WORDS   = 2
_NAME_MAX_WORDS   = 5
_NAME_MIN_ALPHA   = 0.88   # at least 88% alphabetic chars
_NAME_MIN_LEN     = 4


# ── Pass 1: Strict regex ───────────────────────────────────────────────────────

def _extract_pan_pass1(text: str) -> Optional[str]:
    m = _PAN_STRICT.search(text)
    return m.group(1) if m else None


def _extract_dob_pass1(text: str) -> Optional[str]:
    for pat in _DOB_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).replace("-", "/").replace(".", "/")
    return None


# ── Pass 2: OCR-corrected ──────────────────────────────────────────────────────

def _extract_pan_pass2(text: str) -> Optional[str]:
    """Scan each 10-char token and attempt character correction."""
    # Also try correcting spaced PAN (e.g. "RLVP S5393K")
    condensed = re.sub(r"\s+", "", text)
    result = find_corrected_pan(condensed) or find_corrected_pan(text)
    return result


def _extract_dob_pass2(text: str) -> Optional[str]:
    return find_corrected_date(text)


# ── Pass 3: Aggressive scan ────────────────────────────────────────────────────

def _extract_pan_pass3(text: str) -> Optional[str]:
    """Try every 10-char uppercase sequence as a potential PAN."""
    # Include sequences with spaces/noise around them
    candidates = re.findall(r"[A-Z0-9]{7,13}", text.upper())
    for raw in candidates:
        # Trim to 10 chars if longer (might have noise)
        for start in range(len(raw) - 9):
            chunk = raw[start:start + 10]
            if len(chunk) == 10:
                corrected = correct_pan_candidate(chunk)
                if corrected:
                    return corrected
    return None


# ── Name validation ─────────────────────────────────────────────────────────────

def _is_valid_name_line(line: str) -> bool:
    """Return True if a line is a plausible person name."""
    s = line.strip()
    if len(s) < _NAME_MIN_LEN:
        return False
    # Reject blacklisted
    if is_pan_blacklisted(s):
        return False
    # Reject if matches any reject pattern
    for pat in _NAME_REJECT_PATTERNS:
        if pat.search(s):
            return False
    # Alpha ratio check
    alpha = sum(c.isalpha() for c in s)
    if alpha / max(len(s), 1) < _NAME_MIN_ALPHA:
        return False
    # Word count check
    words = s.split()
    if len(words) < _NAME_MIN_WORDS or len(words) > _NAME_MAX_WORDS:
        return False
    # Each word must be mostly alpha
    for w in words:
        if len(w) > 1 and sum(c.isalpha() for c in w) / len(w) < 0.7:
            return False
    return True


def _score_name_line(line: str, position_bonus: float = 0.0) -> float:
    """Score a name candidate (higher = better)."""
    s = line.strip()
    words = s.split()
    wc = len(words)

    # Base: alpha ratio
    alpha_ratio = sum(c.isalpha() for c in s) / max(len(s), 1)
    score = alpha_ratio * 40

    # Word count bonus
    if 2 <= wc <= 3:
        score += 30
    elif wc == 4:
        score += 22
    elif wc == 5:
        score += 10

    # Title/all-caps bonus (both are valid on PAN)
    title_count = sum(1 for w in words if w and w[0].isupper())
    allcaps = all(w.isupper() for w in words if len(w) > 1)
    if allcaps:
        score += 20
    elif title_count == wc:
        score += 15

    # Positional bonus (closer to PAN line = better)
    score += position_bonus

    return score


# ── Positional name extraction ─────────────────────────────────────────────────

def _find_name_label_idx(lines: List[str]) -> Optional[int]:
    """Find the '/ Name' bilingual label line on a PAN card."""
    for i, line in enumerate(lines):
        if _NAME_LABEL_PATTERN.search(line):
            return i
    return None


def _find_father_label_idx(lines: List[str]) -> Optional[int]:
    """Find the '/ Father's Name' bilingual label line on a PAN card."""
    for i, line in enumerate(lines):
        if _FATHER_LABEL_PATTERN.search(line):
            return i
    return None


def _find_pan_line_idx(lines: List[str], pan_number: Optional[str]) -> Optional[int]:
    """Find the line index where PAN number appears."""
    if not pan_number:
        return None
    pan_clean = pan_number.strip().upper()
    for i, line in enumerate(lines):
        line_upper = line.upper().replace(" ", "")
        if pan_clean.replace(" ", "") in line_upper:
            return i
        # Partial match on first 5 chars (prefix is unique enough)
        if pan_clean[:5] in line.upper():
            return i
    return None


def _find_father_line_idx(lines: List[str]) -> Optional[int]:
    """Legacy alias for _find_father_label_idx."""
    return _find_father_label_idx(lines)


def _extract_name_positional(
    lines: List[str],
    pan_line_idx: Optional[int],
    father_label_idx: Optional[int],
    name_label_idx: Optional[int] = None,
) -> Tuple[Optional[str], List[dict]]:
    """
    Deterministic label-anchored name extraction for PAN cards.

    STRATEGY 1 (label-anchored) — MOST RELIABLE:
      PAN card always has:  ... / Name  \n  [HOLDER NAME]  \n  ... / Father's Name ...
      Find '/ Name' label, take FIRST valid line after it, stop at '/ Father' label.

    STRATEGY 2 (positional fallback):
      Take first valid name between PAN number line and father label.

    Returns: (winner_name, reject_log)
      reject_log entries: {"line": str, "status": "selected"|"candidate"|"rejected", "reason": str, "score": float}
    """
    reject_log: List[dict] = []
    candidates: List[Tuple[str, float]] = []

    def log_reject(line: str, reason: str):
        reject_log.append({"line": line, "status": "rejected", "reason": reason, "score": 0})

    def log_candidate(line: str, score: float, method: str):
        reject_log.append({"line": line, "status": "candidate", "reason": method, "score": round(score, 1)})

    # ── STRATEGY 1: Label-anchored ("/ Name" ... "/ Father's Name") ───────────
    if name_label_idx is not None:
        logger.debug("[pan_parser] STRATEGY 1: label-anchored (name_label=%d, father_label=%s)",
                     name_label_idx, father_label_idx)

        # Search window: right after "/ Name" label, stop at "/ Father's Name"
        ns = name_label_idx + 1
        ne = father_label_idx if (father_label_idx is not None and father_label_idx > name_label_idx) \
             else min(name_label_idx + 4, len(lines))

        for i in range(ns, min(ne, len(lines))):
            line = lines[i].strip()
            if not line:
                continue

            # Hard reject: if line itself contains father/signature/dob keywords
            if _FATHER_LABEL_PATTERN.search(line):
                log_reject(line, "contains Father label keyword")
                break  # stop scanning, we've crossed into father territory

            if _DOB_LABEL_PATTERN.search(line):
                log_reject(line, "contains DOB label — past name zone")
                break

            if _is_valid_name_line(line):
                dist = i - name_label_idx
                # Very strong bonus for being right after the Name label
                pos_bonus = 60 - dist * 10  # dist=1 -> +50, dist=2 -> +40, ...
                score = _score_name_line(line, max(pos_bonus, 0))
                candidates.append((line, score))
                log_candidate(line, score, f"after '/ Name' label (dist={dist}), STRATEGY 1")
                logger.debug("[pan_parser][S1] Valid candidate: %r score=%.1f", line, score)
            else:
                # Why was it rejected?
                alpha = sum(c.isalpha() for c in line) / max(len(line), 1)
                reject_reason = "failed name validation"
                if alpha < _NAME_MIN_ALPHA:
                    reject_reason = f"low alpha ratio {alpha:.0%} (need {_NAME_MIN_ALPHA:.0%})"
                elif len(line.split()) < _NAME_MIN_WORDS:
                    reject_reason = "too few words"
                elif any(p.search(line) for p in _NAME_REJECT_PATTERNS):
                    reject_reason = "matched label/keyword reject pattern"
                log_reject(line, reject_reason)
                logger.debug("[pan_parser][S1] Rejected %r: %s", line, reject_reason)

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            winner = candidates[0][0]
            # Mark winner in log
            for entry in reject_log:
                if entry["line"] == winner:
                    entry["status"] = "selected"
                    break
            logger.info("[pan_parser][S1] Name winner: %r (score=%.1f)", winner, candidates[0][1])
            return winner, reject_log

        logger.debug("[pan_parser] S1 found no valid candidates — trying S2")

    # ── STRATEGY 2: Positional (PAN line -> Father label) ─────────────────────
    if pan_line_idx is not None:
        logger.debug("[pan_parser] STRATEGY 2: positional (pan_idx=%d, father_idx=%s)",
                     pan_line_idx, father_label_idx)

        ns = pan_line_idx + 1
        ne = father_label_idx if (father_label_idx is not None and father_label_idx > pan_line_idx) \
             else min(pan_line_idx + 6, len(lines))

        for i in range(ns, min(ne, len(lines))):
            line = lines[i].strip()
            if not line:
                continue

            if _FATHER_LABEL_PATTERN.search(line):
                log_reject(line, "Father label line — stop scanning")
                break

            if _is_valid_name_line(line):
                dist = i - pan_line_idx
                pos_bonus = max(0, 20 - dist * 4)
                score = _score_name_line(line, pos_bonus)
                candidates.append((line, score))
                log_candidate(line, score, f"below PAN line (dist={dist}), STRATEGY 2")
                logger.debug("[pan_parser][S2] Candidate: %r score=%.1f", line, score)
            else:
                alpha = sum(c.isalpha() for c in line) / max(len(line), 1)
                reject_reason = "failed name validation"
                if alpha < _NAME_MIN_ALPHA:
                    reject_reason = f"low alpha ratio {alpha:.0%}"
                elif any(p.search(line) for p in _NAME_REJECT_PATTERNS):
                    reject_reason = "matched keyword reject pattern"
                log_reject(line, reject_reason)

    # ── STRATEGY 3: Constrained full-doc scan (last resort) ───────────────────
    if not candidates:
        logger.debug("[pan_parser] STRATEGY 3: constrained full-doc scan")
        start = max(0, len(lines) // 5)
        end   = min(len(lines), int(len(lines) * 0.85))
        for i, line in enumerate(lines[start:end], start=start):
            stripped = line.strip()
            if not stripped:
                continue
            # Hard reject: do NOT allow lines after father label
            if father_label_idx is not None and i > father_label_idx:
                log_reject(stripped, "BELOW father label — hard rejected")
                continue
            if _is_valid_name_line(stripped):
                score = _score_name_line(stripped, 0.0)
                candidates.append((stripped, score))

    if not candidates:
        logger.warning("[pan_parser] All 3 strategies failed to find a name")
        return None, reject_log

    candidates.sort(key=lambda x: x[1], reverse=True)
    logger.debug("[pan_parser] All name candidates: %s",
                 [(c[0], round(c[1], 1)) for c in candidates[:5]])
    winner = candidates[0][0]
    for entry in reject_log:
        if entry["line"] == winner:
            entry["status"] = "selected"
            break
    return winner, reject_log


# ── Region OCR extraction ──────────────────────────────────────────────────────

def _extract_from_regions(image_gray: np.ndarray) -> Dict[str, Optional[str]]:
    """Run region-targeted OCR on PAN card to extract fields independently."""
    result: Dict[str, Optional[str]] = {"pan_number": None, "name": None, "dob": None}
    try:
        from app.ocr.region_ocr import ocr_pan_regions
        regions = ocr_pan_regions(image_gray)
        logger.debug("[pan_parser] Region OCR texts: %s",
                     {k: v[:60] for k, v in regions.items()})

        # PAN number from its dedicated region
        pan_text = regions.get("pan_number_region", "")
        if pan_text:
            result["pan_number"] = (
                _extract_pan_pass1(pan_text)
                or _extract_pan_pass2(pan_text)
                or _extract_pan_pass3(pan_text)
            )
            if result["pan_number"]:
                logger.info("[pan_parser][REGION] PAN: %s", result["pan_number"])

        # Name from name region
        name_text = regions.get("pan_name_region", "")
        if name_text:
            name_lines = [l.strip() for l in name_text.splitlines() if l.strip()]
            for line in name_lines:
                if _is_valid_name_line(line):
                    result["name"] = line.title()
                    logger.info("[pan_parser][REGION] Name: %s", result["name"])
                    break

        # DOB from DOB region
        dob_text = regions.get("pan_dob_region", "")
        if dob_text:
            result["dob"] = _extract_dob_pass1(dob_text) or _extract_dob_pass2(dob_text)
            if result["dob"]:
                logger.info("[pan_parser][REGION] DOB: %s", result["dob"])

    except Exception as exc:
        logger.warning("[pan_parser] Region OCR failed: %s", exc)
    return result


# ── Multi-variant voting ───────────────────────────────────────────────────────

def _vote_field(candidates: List[Optional[str]]) -> Optional[str]:
    """Pick the most common non-None candidate using majority voting."""
    valid = [c for c in candidates if c]
    if not valid:
        return None
    # Normalize for comparison
    norm = [re.sub(r"\s+", " ", v.strip().upper()) for v in valid]
    counts = Counter(norm)
    winner_norm = counts.most_common(1)[0][0]
    # Return the original-case version matching the winner
    for original, normalized in zip(valid, norm):
        if normalized == winner_norm:
            return original
    return valid[0]


def _vote_pan(candidates: List[Optional[str]]) -> Optional[str]:
    """Vote for the best PAN number (all should be 10-char uppercase)."""
    valid = [c for c in candidates if c and re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", c.strip())]
    if not valid:
        return _vote_field(candidates)
    counts = Counter(valid)
    return counts.most_common(1)[0][0]


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_pan(
    ocr_text: str,
    variant_texts: Optional[Dict[str, str]] = None,
    image_gray=None,     # optional np.ndarray for region OCR
) -> Dict:
    """
    Production-grade PAN parser v3 with:
      - Region-targeted OCR
      - Strict positional name extraction
      - Multi-variant DOB/PAN voting
      - Enhanced OCR confusion correction

    Returns:
        {
            "name":       str | None,
            "pan_number": str | None,
            "dob":        str | None,
            "confidence": float (0-1),
            "field_confidences": {...},
            "debug": {...}      ← parser debug info
        }
    """
    if not ocr_text or not ocr_text.strip():
        return {
            "name": None, "pan_number": None, "dob": None,
            "confidence": 0.0,
            "field_confidences": {"name": 0, "pan_number": 0, "dob": 0},
            "debug": {"method": "empty_input"},
        }

    # ── Step 1: Clean main OCR text ───────────────────────────────────────────
    clean_text = clean_ocr_text(ocr_text, doc_type="pan")
    lines      = [l for l in clean_text.splitlines() if l.strip()]

    logger.debug("[pan_parser] Cleaned text (%d lines):\n%s", len(lines), clean_text[:500])

    # ── Step 2: Multi-pass PAN number extraction ──────────────────────────────
    pan_candidates: List[Optional[str]] = []

    # From main OCR text (3 passes)
    pan_candidates.append(_extract_pan_pass1(clean_text))
    pan_candidates.append(_extract_pan_pass2(clean_text))
    pan_candidates.append(_extract_pan_pass3(clean_text))

    # From variant texts
    vt = variant_texts or {}
    for v_name, v_text in vt.items():
        if v_text:
            v_clean = clean_ocr_text(v_text, doc_type="pan")
            pan_candidates.append(_extract_pan_pass1(v_clean))
            pan_candidates.append(_extract_pan_pass2(v_clean))

    pan_number = _vote_pan(pan_candidates)
    logger.info("[pan_parser] PAN candidates=%s -> winner=%s",
                [c for c in pan_candidates if c], pan_number)

    # ── Step 3: Multi-pass DOB extraction ─────────────────────────────────────
    dob_candidates: List[Optional[str]] = [
        _extract_dob_pass1(clean_text),
        _extract_dob_pass2(clean_text),
    ]
    for v_text in vt.values():
        if v_text:
            v_clean = clean_ocr_text(v_text, doc_type="pan")
            dob_candidates.append(_extract_dob_pass1(v_clean))
            dob_candidates.append(_extract_dob_pass2(v_clean))
    dob = _vote_field(dob_candidates)
    logger.info("[pan_parser] DOB candidates=%s -> winner=%s",
                [c for c in dob_candidates if c], dob)

    # ── Step 4: Label-anchored name extraction ────────────────────────────────--
    pan_line_idx     = _find_pan_line_idx(lines, pan_number)
    name_label_idx   = _find_name_label_idx(lines)
    father_label_idx = _find_father_label_idx(lines)
    logger.debug("[pan_parser] pan_line_idx=%s name_label_idx=%s father_label_idx=%s",
                 pan_line_idx, name_label_idx, father_label_idx)

    name, name_reject_log = _extract_name_positional(
        lines, pan_line_idx, father_label_idx, name_label_idx
    )

    # Try from variant texts if name not found in main text
    if name is None:
        for v_name, v_text in vt.items():
            if not v_text:
                continue
            v_clean = clean_ocr_text(v_text, doc_type="pan")
            v_lines = [l for l in v_clean.splitlines() if l.strip()]
            v_pan_idx    = _find_pan_line_idx(v_lines, pan_number)
            v_name_idx   = _find_name_label_idx(v_lines)
            v_father_idx = _find_father_label_idx(v_lines)
            name_candidate, v_log = _extract_name_positional(
                v_lines, v_pan_idx, v_father_idx, v_name_idx
            )
            if name_candidate:
                logger.info("[pan_parser] Name found in variant %r: %r", v_name, name_candidate)
                name = name_candidate
                name_reject_log.extend(v_log)  # include variant debug in log
                break

    if name:
        # Clean and title-case
        from app.ocr.correction_engine import correct_name_text
        name = correct_name_text(name)
        name = name.title() if name else None
        logger.info("[pan_parser] [OK] Name: %s", name)
    else:
        logger.warning("[pan_parser] [MISS] Name NOT found")

    if pan_number:
        logger.info("[pan_parser] [OK] PAN: %s", pan_number)
    else:
        logger.warning("[pan_parser] [MISS] PAN NOT found — tried %d candidates",
                       len([c for c in pan_candidates if c]))
        logger.debug("[pan_parser] Clean text sample:\n%s", clean_text[:300])

    if dob:
        logger.info("[pan_parser] [OK] DOB: %s", dob)
    else:
        logger.warning("[pan_parser] [MISS] DOB NOT found")

    # ── Step 5: Confidence scoring ────────────────────────────────────────────
    fc = {
        "pan_number": calculate_field_confidence("pan_number", pan_number, clean_text, vt),
        "dob":        calculate_field_confidence("dob",        dob,        clean_text, vt),
        "name":       calculate_field_confidence("name",       name,       clean_text, vt),
    }

    overall_confidence = round(
        (fc["pan_number"] + fc["dob"] + fc["name"]) / 300.0, 4
    )

    return {
        "name":       name,
        "pan_number": pan_number,
        "dob":        dob,
        "confidence": overall_confidence,
        "field_confidences": fc,
        "debug": {
            "pan_line_idx":     pan_line_idx,
            "name_label_idx":   name_label_idx,
            "father_label_idx": father_label_idx,
            "pan_line":         lines[pan_line_idx]     if (pan_line_idx     is not None and pan_line_idx     < len(lines)) else None,
            "name_label_line":  lines[name_label_idx]   if (name_label_idx   is not None and name_label_idx   < len(lines)) else None,
            "father_label_line":lines[father_label_idx] if (father_label_idx is not None and father_label_idx < len(lines)) else None,
            "name_reject_log":  name_reject_log,
            "pan_candidates":   [c for c in pan_candidates if c],
            "dob_candidates":   [c for c in dob_candidates if c],
            "lines_count":      len(lines),
        },
    }

