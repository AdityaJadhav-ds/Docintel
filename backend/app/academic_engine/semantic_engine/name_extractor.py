"""
name_extractor.py — NAME EXTRACTION STABILIZATION MODULE v2
=============================================================
Dedicated engine for extracting candidate names from Maharashtra
SSC/HSC marksheets (1988–2022).

Design rules (IMMUTABLE):
  - BETTER TO RETURN NULL THAN WRONG NAME.
  - Never penalise uppercase (old SSC docs are ALL CAPS).
  - Hard-reject any value containing organisational keywords.
  - Fuzzy-match labels because OCR corrupts them.
  - Geometric extraction only within bounded region near label.
  - Supports multiline names (surname on one line, given name below).
  - OCR character repair applied ONLY on names, AFTER scoring check.
  - Full debug JSON written per extraction for observability.

Target outputs:
  "PUANNA GIRISHKUMAR GHANASHAM"
  "LANDAGE SUNIL MANOHAR"
  "Jadhav Aditya Bhagvan"

NOT:
  "Maharashtra State Board"
  "Statement Of Marks"
"""
import re
import json
import math
import logging
import os
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("docvalidator")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — NAME LABEL DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

# English name-field labels (sorted longest-first to prefer specific matches)
_ENGLISH_LABELS: List[str] = [
    "candidate's full name",
    "candidate full name",
    "candidates full name",
    "name of the candidate",
    "name of candidate",
    "candidate name",
    "student's name",
    "student name",
    "full name",
    "surname first",
    "beginning with surname",
    "name beginning",
    "this is to certify that",
    "certify that",
    # bare "name" kept LAST — lowest priority, short label prone to false hits
    "name",
]

# Marathi name-field labels
_MARATHI_LABELS: List[str] = [
    "उमेदवाराचे संपूर्ण नाव",
    "उमेदवाराचे",
    "संपूर्ण नाव",
    "आडनाव प्रथम",
    "नाव",
]

_ALL_LABELS: List[str] = _ENGLISH_LABELS + _MARATHI_LABELS

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — ORGANISATION REJECTION  (hard-reject set)
# ─────────────────────────────────────────────────────────────────────────────

# These are WHOLE-WORD matches — "state" must appear as a word, not a substring.
# Using word-boundary check in _is_org_text().
_ORG_KEYWORDS_EXACT: List[str] = [
    'board', 'education', 'secondary', 'certificate', 'statement',
    'school', 'college', 'university', 'division', 'divisional', 'state',
    'maharashtra', 'msbshse', 'pune', 'mumbai', 'nashik', 'kolhapur',
    'nagpur', 'aurangabad', 'institute', 'higher', 'council', 'examination',
    'marksheet', 'marks', 'senior', 'junior', 'technical', 'polytechnic',
    'result', 'pass', 'fail', 'distinction',
    'percentage', 'grade', 'subject',
]

# Substring matches (these cannot appear ANYWHERE in the candidate)
_ORG_KEYWORDS_SUBSTR: List[str] = [
    'msbshse', 'cbse', 'icse', 'neet', 'jee',
]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — OCR REPAIR MAP (names only)
# ─────────────────────────────────────────────────────────────────────────────

_OCR_NAME_REPAIR: Dict[str, str] = {
    '0': 'O',   # zero → O
    '1': 'I',   # one  → I  (ALL-CAPS names only)
    '5': 'S',   # five → S
    '8': 'B',   # eight → B
    '$': 'S',
    '|': 'I',
    '@': 'A',
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — FUZZY LABEL MATCHING
# ─────────────────────────────────────────────────────────────────────────────

def _fuzzy_label_score(text: str, label: str) -> float:
    """
    Returns similarity score [0.0, 1.0] between an OCR line and a known label.
    Uses word-overlap + bigram Jaccard.  Score >= threshold → label hit.

    Key fix vs v1:
      - Bare "name" label requires the word to appear as a standalone token,
        not as a substring of another word (e.g. "surname" should not match "name").
      - Longer labels get a small bonus to prefer specific matches.
    """
    t = text.lower().strip()
    l = label.lower().strip()

    if not t or not l:
        return 0.0

    # Exact substring match → full score (but see bare-name guard below)
    if l in t:
        # Guard: bare "name" label must be a whole word, not part of "surname"
        if label == "name":
            if not re.search(r'\bname\b', t):
                return 0.0
        return 1.0

    # Normalise: strip punctuation
    t_clean = re.sub(r"[^a-z\u0900-\u097f\s]", " ", t)
    l_clean = re.sub(r"[^a-z\u0900-\u097f\s]", " ", l)

    l_words = l_clean.split()
    t_words = set(t_clean.split())
    if not l_words:
        return 0.0

    # Word overlap
    matched = sum(1 for w in l_words if w in t_words or any(w in tw for tw in t_words))
    word_score = matched / len(l_words)

    # Bigram Jaccard
    def bigrams(s: str):
        s = s.replace(" ", "")
        return set(s[i:i+2] for i in range(len(s) - 1))

    t_bi = bigrams(t_clean)
    l_bi = bigrams(l_clean)
    if not t_bi or not l_bi:
        bigram_score = 0.0
    else:
        inter = len(t_bi & l_bi)
        union = len(t_bi | l_bi)
        bigram_score = inter / union if union else 0.0

    return 0.6 * word_score + 0.4 * bigram_score


def detect_name_labels(lines: List[dict], threshold: float = 0.68) -> List[dict]:
    """
    STEP 1 — Scan reconstructed lines, return those matching name labels.

    KEY FIX (B.Tech marksheets):
      Many marksheets have 'Name' and 'Mother Name' on ONE line:
        "Name  SHAIKH MUSKAN NAJIR   Mother Name  NURJAHAN"
      Old code excluded the entire line because 'mother' was present.
      New code: split at 'Mother/Father', check only the LEFT part for the label.

    Returns List[dict] sorted by score desc.
    """
    _SPLIT_RE = re.compile(r'\b(?:mother|father|aai|baba|parent)\b', re.IGNORECASE)
    # Labels that mean this IS a mother/father label line (not a candidate label)
    _PURE_EXCLUDE_RE = re.compile(
        r'^(?:mother|father|aai|baba|parent)\s*(name|नाव)?',
        re.IGNORECASE,
    )

    matches = []
    for line in lines:
        text = line.get("text", "")

        # Split at first occurrence of mother/father
        split_m = _SPLIT_RE.search(text)
        if split_m:
            left = text[:split_m.start()].strip()
            # If nothing useful left of split, or left starts with mother/father word itself → skip
            if not left or _PURE_EXCLUDE_RE.match(left):
                continue
            check_text = left
        else:
            check_text = text

        if not check_text.strip():
            continue

        best_score = 0.0
        best_label = None
        for label in _ALL_LABELS:
            score = _fuzzy_label_score(check_text, label)
            if score > best_score:
                best_score = score
                best_label = label

        if best_score >= threshold:
            specificity = len(best_label.split()) / 5.0
            # Store _name_stop_at so geometric extractor can clamp the value region
            trimmed = {**line, "_name_stop_at": split_m.start() if split_m else None}
            matches.append({
                "line":          trimmed,
                "label_matched": best_label,
                "score":         round(best_score, 3),
                "specificity":   round(min(specificity, 1.0), 3),
                "bbox":          line.get("bbox", (0, 0, 0, 0)),
            })

    matches.sort(key=lambda m: (m["specificity"], m["score"]), reverse=True)
    return matches


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — ORGANISATION REJECTION
# ─────────────────────────────────────────────────────────────────────────────

def _is_org_text(text: str) -> Tuple[bool, str]:
    """Returns (is_rejected, reason). Uses word-boundary matching."""
    t_lower = text.lower()
    # Substring match for abbreviation-style keywords
    for kw in _ORG_KEYWORDS_SUBSTR:
        if kw in t_lower:
            return True, f"Contains org substring: '{kw}'"
    # Whole-word match for common English words
    for kw in _ORG_KEYWORDS_EXACT:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, t_lower):
            return True, f"Contains org word: '{kw}'"
    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — OCR REPAIR (names only)
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_repair_name(text: str) -> str:
    """
    Fix known OCR character confusions in name strings.
    Only applied when text is predominantly alphabetic (majority alpha chars).
    Applied AFTER scoring to avoid corrupting non-name strings.
    """
    if not text:
        return text

    alpha_ratio = sum(c.isalpha() for c in text) / max(len(text), 1)
    if alpha_ratio < 0.50:
        return text  # Don't repair non-name strings

    result = list(text)
    for i, ch in enumerate(result):
        if ch in _OCR_NAME_REPAIR:
            result[i] = _OCR_NAME_REPAIR[ch]
    return "".join(result)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — NAME STRUCTURE SCORING
# ─────────────────────────────────────────────────────────────────────────────

def _score_name_candidate(text: str, label_proximity: float = 0.0) -> float:
    """
    Score a name candidate string.  Higher = better.
    Returns -999.0 for immediate hard-rejects.

    label_proximity: 0.0 (no context) → 1.0 (adjacent to label)

    Good:
      - 2–4 words, alphabetic, near label, uppercase OR titlecase
    Bad:
      - Too long, numeric, huge paragraph, mixed symbols
    """
    if not text or not text.strip():
        return -999.0

    t = text.strip()

    # ── Hard reject: organisational text ──────────────────────
    is_org, reason = _is_org_text(t)
    if is_org:
        return -999.0

    # ── Hard reject: more than 2 digits ───────────────────────
    digit_count = sum(c.isdigit() for c in t)
    if digit_count > 2:
        return -999.0

    # ── Hard reject: contains symbols ─────────────────────────
    if re.search(r'[/\\|@#$%^&*(){}\[\]<>=+~`]', t):
        return -999.0

    # ── Hard reject: too many words (paragraph, not a name) ───
    words = t.split()
    if len(words) > 6:
        return -999.0

    # ── Hard reject: too short ────────────────────────────────
    if len(t.replace(" ", "")) < 3:
        return -999.0

    # ── Hard reject: contains label-like fragments ────────────
    label_fragment_re = re.compile(
        r'\b(?:candidate|student|full\s+name|surname|father|mother|'
        r'आईचे|father.?s)\b',
        re.IGNORECASE
    )
    if label_fragment_re.search(t):
        return -999.0

    score = 0.0

    # ── Positive: word count ──────────────────────────────────
    if 2 <= len(words) <= 4:
        score += 5.0
    elif len(words) == 1 and len(t) >= 5:
        score += 1.5
    elif len(words) == 5:
        score += 3.0  # 5-word names are rare but possible

    # ── Positive: case pattern ────────────────────────────────
    # STEP 4: Do NOT penalise uppercase — old SSC names are ALL CAPS
    if t.istitle():
        score += 4.0                          # "Jadhav Aditya Bhagvan"
    elif t.isupper() and len(t) > 3:
        score += 3.5                          # "LANDAGE SUNIL MANOHAR"
    elif t[0].isupper():
        score += 1.0                          # mixed case — slight boost

    # ── Positive: purely alphabetic ───────────────────────────
    if t.replace(" ", "").isalpha():
        score += 3.0

    # ── Positive: realistic word lengths ─────────────────────
    if len(words) >= 2:
        avg_word_len = sum(len(w) for w in words) / len(words)
        if 3.0 <= avg_word_len <= 12.0:
            score += 1.5

    # ── Positive: proximity to name label ─────────────────────
    score += label_proximity * 6.0

    # ── Negative: has any digits ──────────────────────────────
    if digit_count > 0:
        score -= 8.0

    # ── Negative: 5–6 word names ──────────────────────────────
    if len(words) == 5:
        score -= 1.0
    elif len(words) == 6:
        score -= 2.0

    return score


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — GEOMETRIC EXTRACTION (bounded region near label)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_near_label(
    label_line: dict,
    all_lines: List[dict],
    max_right_dist: int = 700,
    max_below_dist: int = 150,
) -> List[dict]:
    """
    STEP 2 — Search only immediate right and immediate below the label.
    Does NOT search the whole document.

    KEY FIX: if label_line has '_name_stop_at', clamp right-side extraction
    so we don't pick up 'Mother Name NURJAHAN' from the same text line.

    Returns list of {text, bbox, direction, distance}.
    """
    lx, ly, lw, lh = label_line.get("bbox", (0, 0, 0, 0))
    label_right  = lx + lw
    label_bottom = ly + lh

    # If Name and Mother appear on same OCR line, estimate pixel X-limit
    stop_at_char = label_line.get("_name_stop_at")
    line_text     = label_line.get("text", "")
    max_x_clamp   = None
    if stop_at_char is not None and line_text:
        # Estimate x-position of the 'Mother' word using character fraction
        frac = stop_at_char / max(len(line_text), 1)
        max_x_clamp = lx + int(lw * frac) if lw > 0 else None

    candidates = []
    for line in all_lines:
        if line is label_line:
            continue

        tx, ty, tw, th = line.get("bbox", (0, 0, 0, 0))
        text = line.get("text", "").strip()
        if not text:
            continue

        # ── Right: same row (Y overlap), starts after label ───
        y_overlap    = abs(ty - ly) < lh * 1.3
        starts_right = tx >= label_right - 15

        if y_overlap and starts_right:
            dist = tx - label_right
            # Clamp: skip if this word starts past the Mother/Father split
            if max_x_clamp is not None and tx >= max_x_clamp:
                continue
            if 0 <= dist <= max_right_dist:
                candidates.append({
                    "text":      text,
                    "bbox":      (tx, ty, tw, th),
                    "direction": "right",
                    "distance":  dist,
                })

        # ── Below: roughly same X alignment, just below ───────
        below        = ty >= label_bottom - 8
        x_aligned    = abs(tx - lx) < max(lw + 60, 120)
        vertical_dist = ty - label_bottom

        if below and x_aligned and 0 <= vertical_dist <= max_below_dist:
            candidates.append({
                "text":      text,
                "bbox":      (tx, ty, tw, th),
                "direction": "below",
                "distance":  vertical_dist,
            })

    # Right candidates first (prefer same-line), then by distance
    candidates.sort(key=lambda c: (0 if c["direction"] == "right" else 1, c["distance"]))
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — MULTILINE MERGING
# ─────────────────────────────────────────────────────────────────────────────

def _merge_multiline_name(first_line: dict, all_lines: List[dict], max_gap: int = 70) -> str:
    """
    STEP 3 — Merge vertically aligned text blocks that form a single name.

    Example:
      Line 1: "LANDAGE"           → surname
      Line 2: "SUNIL MANOHAR"     → given names
      Result: "LANDAGE SUNIL MANOHAR"

    Stops merging when:
      - Next line is an org keyword
      - Next line contains >2 digits
      - Vertical gap is too large
      - Next line appears to be a label
      - Accumulated word count >= 5 (name is complete)
    """
    fx, fy, fw, fh = first_line.get("bbox", (0, 0, 0, 0))
    merged = [first_line.get("text", "").strip()]
    last_bottom = fy + fh

    below_lines = [
        l for l in all_lines
        if l is not first_line and l.get("bbox", (0, 0, 0, 0))[1] > fy
    ]
    below_lines.sort(key=lambda l: l["bbox"][1])

    for line in below_lines:
        tx, ty, tw, th = line.get("bbox", (0, 0, 0, 0))
        text = line.get("text", "").strip()

        if not text:
            continue

        gap = ty - last_bottom
        if gap > max_gap:
            break

        # Stop if this looks like a label line
        is_label = any(_fuzzy_label_score(text, lbl) >= 0.65 for lbl in _ALL_LABELS)
        if is_label:
            break

        # Stop if organisational text
        is_org, _ = _is_org_text(text)
        if is_org:
            break

        # Stop if contains many digits (numeric row)
        digit_count = sum(c.isdigit() for c in text)
        if digit_count > 2:
            break

        # Stop if x-alignment drifts too much (>200px from first line)
        if abs(tx - fx) > 200:
            break

        merged.append(text)
        last_bottom = ty + th

        # Stop when we have 5+ words (name is complete)
        total_words = sum(len(m.split()) for m in merged)
        if total_words >= 5:
            break

    return " ".join(merged)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 9 — FALLBACK: TOP-CENTRE REGION SCAN
# ─────────────────────────────────────────────────────────────────────────────

def _top_centre_fallback(
    lines: List[dict],
    doc_width: int = 800,
    doc_height: int = 1200,
) -> Optional[str]:
    """
    STEP 9 — If no label was found, scan the top-middle region.
    Most SSC/HSC marksheets place names there.

    Region:
      y: [10%, 40%] of page height
      x: centre ± 40% of page width  (tighter than v1 to avoid margin noise)
    """
    y_top = doc_height * 0.10
    y_bottom = doc_height * 0.40
    x_centre = doc_width / 2
    x_margin = doc_width * 0.40  # ±40% from centre

    candidates = []
    for line in lines:
        tx, ty, tw, th = line.get("bbox", (0, 0, 0, 0))
        text = line.get("text", "").strip()

        if not (y_top <= ty <= y_bottom):
            continue

        line_centre = tx + tw / 2
        if abs(line_centre - x_centre) > x_margin:
            continue

        score = _score_name_candidate(text, label_proximity=0.2)
        if score > 2.0:
            candidates.append({"text": text, "score": score, "bbox": (tx, ty, tw, th)})

    if not candidates:
        return None

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — DEBUG OUTPUT WRITER
# ─────────────────────────────────────────────────────────────────────────────

_DEBUG_OUT_PATH = os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "logs", "debug_name_pipeline.json"
)


def _write_name_debug(debug: dict) -> None:
    """STEP 8 — Write debug_name_pipeline.json for post-mortem analysis."""
    try:
        os.makedirs(os.path.dirname(_DEBUG_OUT_PATH), exist_ok=True)
        with open(_DEBUG_OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(debug, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning("[name_extractor] Could not write debug JSON: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN NAME EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

class NameExtractor:
    """
    Dedicated candidate name extractor for Maharashtra SSC/HSC marksheets.

    Usage:
        extractor = NameExtractor()
        result = extractor.extract(lines, ocr_words)
        # result: {"value": "LANDAGE SUNIL MANOHAR", "confidence": 0.92, ...}
    """

    def extract(self, lines: List[dict], ocr_words: List[dict]) -> dict:
        """
        Full extraction pipeline.
        Returns field dict, or {"_name_debug": debug} if no confident name found.
        BETTER TO RETURN NULL THAN WRONG NAME.
        """
        debug: Dict[str, Any] = {
            "labels_found": [],
            "candidate_regions": [],
            "rejected_candidates": [],
            "fallback_used": False,
            "final_name": None,
            "final_score": None,
        }

        if not lines:
            _write_name_debug(debug)
            return {}

        # Estimate document dimensions from OCR bboxes
        all_x = [w["bbox"][0] + w["bbox"][2] for w in ocr_words if "bbox" in w]
        all_y = [w["bbox"][1] + w["bbox"][3] for w in ocr_words if "bbox" in w]
        doc_width  = max(all_x) if all_x else 800
        doc_height = max(all_y) if all_y else 1200

        # ── STEP 1: Detect name labels ────────────────────────
        label_hits = detect_name_labels(lines)
        debug["labels_found"] = [
            {
                "text": h["line"]["text"],
                "label": h["label_matched"],
                "score": h["score"],
                "specificity": h["specificity"],
            }
            for h in label_hits
        ]

        best_name: Optional[str] = None
        best_score: float = -999.0

        # ── STEP 2 & 3: Geometric extraction + multiline merge ─
        for hit in label_hits:
            label_line  = hit["line"]
            label_score = hit["score"]

            # STEP 2: Get candidates in bounded region near label
            near = _extract_near_label(label_line, lines)

            # KEY FIX: If the label line itself contains the name (e.g. "Name: SHAIKH MUSKAN"),
            # extract the text portion AFTER the label keyword on the same line.
            label_text = hit["label_matched"]
            full_text  = label_line.get("text", "")
            stop_at    = label_line.get("_name_stop_at")

            # Use the portion before 'Mother Name' if it exists
            check_text = full_text[:stop_at] if stop_at is not None else full_text

            # Try to find the name after the label on the same line
            # e.g. "Name : SHAIKH MUSKAN NAJIR"
            m = re.search(re.escape(label_text) + r'\s*[:.-]*\s*(.*)', check_text, re.IGNORECASE)
            if m:
                same_line_val = m.group(1).strip()
                if same_line_val and len(same_line_val) >= 3:
                    near.insert(0, {
                        "text":          same_line_val,
                        "bbox":          label_line.get("bbox", (0, 0, 0, 0)),
                        "direction":     "right",
                        "distance":      0,
                        "is_same_line":  True,
                    })

            for cand in near:
                raw_text = cand["text"]

                debug_entry: Dict[str, Any] = {
                    "raw": raw_text,
                    "direction": cand["direction"],
                    "distance": cand["distance"],
                    "label": hit["label_matched"],
                    "label_score": label_score,
                }

                # ── STEP 5: Org rejection ──────────────────────
                is_org, org_reason = _is_org_text(raw_text)
                if is_org:
                    debug_entry["rejected"] = True
                    debug_entry["reason"]   = org_reason
                    debug["rejected_candidates"].append(debug_entry)
                    continue

                # ── STEP 6: Score the raw text FIRST ──────────
                # Proximity: right = 1.0, below = 0.85, weighted by label confidence
                proximity = (1.0 if cand["direction"] == "right" else 0.85) * label_score
                raw_score = _score_name_candidate(raw_text, label_proximity=proximity)

                if raw_score <= 0:
                    debug_entry["rejected"] = True
                    debug_entry["reason"]   = f"Raw score too low: {raw_score:.2f}"
                    debug["rejected_candidates"].append(debug_entry)
                    continue

                # ── STEP 3: Multiline merge ────────────────────
                cand_line = next(
                    (l for l in lines if l.get("text", "").strip() == raw_text),
                    None
                )
                if cand_line:
                    merged = _merge_multiline_name(cand_line, lines)
                else:
                    merged = raw_text

                # ── STEP 7: OCR repair AFTER scoring ──────────
                merged_repaired = _ocr_repair_name(merged)

                # Final score on merged+repaired string
                final_score = _score_name_candidate(merged_repaired, label_proximity=proximity)

                debug_entry["merged"]      = merged_repaired
                debug_entry["score"]       = round(final_score, 3)

                if final_score <= 0:
                    debug_entry["rejected"] = True
                    debug_entry["reason"]   = f"Merged score too low: {final_score:.2f}"
                    debug["rejected_candidates"].append(debug_entry)
                    continue

                debug_entry["accepted"] = True
                debug["candidate_regions"].append(debug_entry)

                if final_score > best_score:
                    best_score = final_score
                    best_name  = merged_repaired

        # ── STEP 9: Fallback — top-centre region scan ─────────
        if best_name is None:
            fallback = _top_centre_fallback(lines, doc_width, doc_height)
            if fallback:
                fallback_repaired = _ocr_repair_name(fallback)
                fallback_score    = _score_name_candidate(fallback_repaired, label_proximity=0.2)
                if fallback_score > 2.5:   # higher threshold for fallback
                    best_name  = fallback_repaired
                    best_score = fallback_score
                    debug["fallback_used"] = True
                    debug["candidate_regions"].append({
                        "raw":       fallback,
                        "merged":    fallback_repaired,
                        "score":     round(fallback_score, 3),
                        "direction": "top_centre_fallback",
                        "accepted":  True,
                    })

        # ── STEP 8: Write debug JSON ───────────────────────────
        debug["final_name"]  = best_name
        debug["final_score"] = round(best_score, 3) if best_score > -999 else None
        _write_name_debug(debug)

        logger.debug(
            "[name_extractor] result=%s score=%.2f labels=%d rejected=%d fallback=%s",
            best_name,
            best_score if best_score > -999 else 0.0,
            len(debug["labels_found"]),
            len(debug["rejected_candidates"]),
            debug["fallback_used"],
        )

        if best_name is None:
            return {"_name_debug": debug}

        # Normalise confidence: realistic max score ~14 → 0.97
        normalized_conf = min(0.97, max(0.30, best_score / 14.0))

        return {
            "value": best_name,
            "confidence": round(normalized_conf, 3),
            "extraction_strategy": "name_extractor_v2",
            "source_label": (
                debug["labels_found"][0]["label"]
                if debug["labels_found"] else "top_centre_fallback"
            ),
            "source_region": (0, 0, 0, 0),
            "_name_debug": debug,
        }
