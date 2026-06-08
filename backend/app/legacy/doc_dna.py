"""
app/extraction/doc_dna.py
===========================
Document DNA Engine — Structural Signatures for Indian Documents.

Phase 3 — Priority 2.

NOT a hard classifier. Returns soft structural signals only.
Used to improve:
    - table reconstruction hints
    - field alignment expectations
    - column count hints
    - OCR language priority
    - rendering strategy

Supported DNA signatures:
    aadhaar         — 12-digit ID, biometric fields, Hindi/Devanagari
    pan             — 10-char alphanumeric pattern, name/DOB/father
    bank_statement  — High table density, currency ₹, account patterns
    invoice         — GST/GSTIN, item table, total/subtotal
    marksheet       — Subject/marks table, percentage, institution header
    ration_card     — Handwritten fields, ration keywords, multi-script
    government_doc  — Stamps, seals, multi-script, official keywords
    passport        — MRZ-like patterns, country codes, travel doc

Each signature returns confidence 0.0–0.95 (never 1.0).
Soft hints are used downstream to tune reconstruction.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

try:
    from app.core.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ── Regex patterns per document type ──────────────────────────────────────────

_PATTERNS: Dict[str, List[Tuple[str, float, re.Pattern]]] = {
    "aadhaar": [
        ("12_digit_number",   0.40, re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
        ("xxxx_masked",       0.25, re.compile(r"\bXXXX\s?XXXX\s?\d{4}\b")),
        ("aadhaar_keyword",   0.15, re.compile(r"(?i)\b(aadhaar|आधार|uid|uidai|unique\s*identification)\b")),
        ("dob_field",         0.10, re.compile(r"(?i)\b(dob|date\s+of\s+birth|जन्म\s*तिथि)\b")),
        ("address_field",     0.10, re.compile(r"(?i)\b(address|पता|s/o|d/o|w/o|c/o)\b")),
    ],
    "pan": [
        ("pan_pattern",       0.45, re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
        ("pan_keyword",       0.20, re.compile(r"(?i)\b(permanent\s*account|income\s*tax|pan\s*card|आयकर)\b")),
        ("father_field",      0.15, re.compile(r"(?i)\b(father|father\'s\s*name|पिता|s/o)\b")),
        ("dob_field",         0.10, re.compile(r"(?i)\b(dob|date\s+of\s+birth)\b")),
        ("govt_india",        0.10, re.compile(r"(?i)\b(government\s+of\s+india|भारत\s+सरकार|income\s+tax\s+department)\b")),
    ],
    "bank_statement": [
        ("account_number",    0.20, re.compile(r"(?i)\b(a/?c|account\s*no|acc\s*no)[\s:]+\d{8,18}\b")),
        ("transaction_row",   0.25, re.compile(r"(?i)\b(dr|cr|debit|credit|neft|rtgs|imps|upi|atm)\b")),
        ("currency_amount",   0.20, re.compile(r"[₹]\s*[\d,]+\.?\d{0,2}")),
        ("balance_keyword",   0.15, re.compile(r"(?i)\b(balance|closing|opening|available)\b")),
        ("date_amount_pair",  0.10, re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+[\d,.]+")),
        ("ifsc_code",         0.10, re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ],
    "invoice": [
        ("gstin_pattern",     0.30, re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")),
        ("invoice_keyword",   0.20, re.compile(r"(?i)\b(invoice|bill|receipt|challan|tax\s*invoice|proforma)\b")),
        ("gst_keyword",       0.15, re.compile(r"(?i)\b(gst|cgst|sgst|igst|hsn|sac)\b")),
        ("total_keyword",     0.15, re.compile(r"(?i)\b(total|grand\s+total|subtotal|amount\s+due|net\s+amount)\b")),
        ("item_table",        0.10, re.compile(r"(?i)\b(qty|quantity|unit|price|rate|discount)\b")),
        ("tax_amount",        0.10, re.compile(r"(?i)(tax|%)[\s:]+[\d,.]+")),
    ],
    "marksheet": [
        ("marks_pattern",     0.25, re.compile(r"(?i)\b(marks|score|grade|gpa|cgpa|percentage|pass|fail)\b")),
        ("subject_pattern",   0.20, re.compile(r"(?i)\b(subject|paper|theory|practical|total\s+marks)\b")),
        ("result_keyword",    0.20, re.compile(r"(?i)\b(result|declaration|exam|examination|university|board)\b")),
        ("roll_number",       0.15, re.compile(r"(?i)\b(roll\s*(no|number)|enrollment|reg(istration)?\s*(no|number))\b")),
        ("numeric_table_row", 0.10, re.compile(r"\d{2,3}\s*/\s*\d{2,3}")),
        ("division_keyword",  0.10, re.compile(r"(?i)\b(first|second|third)\s+division\b")),
    ],
    "ration_card": [
        ("ration_keyword",    0.35, re.compile(r"(?i)\b(ration|राशन|fair\s+price|ration\s+card|bpl|apl)\b")),
        ("family_head",       0.20, re.compile(r"(?i)\b(head\s+of\s+family|परिवार\s+के\s+मुखिया|family\s+member)\b")),
        ("shop_pattern",      0.15, re.compile(r"(?i)\b(fair\s+price\s+shop|fps|ration\s+shop|dealer)\b")),
        ("state_govt",        0.15, re.compile(r"(?i)\b(state\s+government|राज्य\s+सरकार|district|tehsil|taluka)\b")),
        ("ration_items",      0.15, re.compile(r"(?i)\b(wheat|rice|sugar|kerosene|dal|गेहूं|चावल|चीनी)\b")),
    ],
    "government_doc": [
        ("govt_header",       0.25, re.compile(r"(?i)\b(government\s+of|ministry|department\s+of|official|gazette|notification)\b")),
        ("seal_keyword",      0.15, re.compile(r"(?i)\b(seal|stamp|office\s+of|under\s+secretary|section\s+officer)\b")),
        ("order_number",      0.15, re.compile(r"(?i)\b(order|circular|memorandum|letter|no\.)\s+\d")),
        ("designation",       0.20, re.compile(r"(?i)\b(collector|magistrate|tehsildar|officer|director|commissioner)\b")),
        ("official_ref",      0.15, re.compile(r"(?i)\b(ref\.?\s*no|file\s*no|dated|subject)\b")),
        ("salutation",        0.10, re.compile(r"(?i)\b(to\s+whomsoever|this\s+is\s+to\s+certify|certified\s+that)\b")),
    ],
    "passport": [
        ("passport_keyword",  0.25, re.compile(r"(?i)\b(passport|travel\s+document|republic\s+of\s+india)\b")),
        ("mrz_pattern",       0.35, re.compile(r"[A-Z<]{9,}")),
        ("nationality",       0.15, re.compile(r"(?i)\b(nationality|ind|indian)\b")),
        ("visa_page",         0.10, re.compile(r"(?i)\b(visa|entry|departure|immigration)\b")),
        ("validity",          0.15, re.compile(r"(?i)\b(valid\s+until|expiry|expires|date\s+of\s+issue)\b")),
    ],
}

# ── Feature Extraction ─────────────────────────────────────────────────────────

def compute_dna_features(
    text:          str,
    blocks:        List[Dict],
    page_analysis: Dict,
) -> Dict:
    """
    Compute structural features of the document for DNA matching.
    Pure text + block structure analysis — no image processing.
    """
    if not text:
        text = ""

    words = text.split()
    chars = list(text)
    lines = [l for l in text.splitlines() if l.strip()]

    word_count  = len(words)
    line_count  = len(lines)
    char_count  = len(chars)

    # Script ratios
    devanagari_chars = sum(1 for c in chars if "\u0900" <= c <= "\u097F")
    latin_chars      = sum(1 for c in chars if c.isascii() and c.isalpha())
    digit_chars      = sum(1 for c in chars if c.isdigit())

    devanagari_ratio = devanagari_chars / max(char_count, 1)
    numeric_ratio    = digit_chars      / max(char_count, 1)
    latin_ratio      = latin_chars      / max(char_count, 1)

    # Table density
    table_blocks   = [b for b in blocks if b.get("type") == "table"]
    table_rows     = sum(len(b.get("rows", [])) for b in table_blocks)
    total_blocks   = max(len(blocks), 1)
    table_density  = len(table_blocks) / total_blocks

    # Currency & financial markers
    currency_present = bool(re.search(r"[₹$€£]", text))
    has_currency_amt = bool(re.search(r"[₹]\s*[\d,]+", text))

    # Key ID patterns
    has_12digit   = bool(re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", text))
    has_pan       = bool(re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text))
    has_gstin     = bool(re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", text))
    has_ifsc      = bool(re.search(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", text))
    has_mrz       = bool(re.search(r"[A-Z<]{9,}", text))

    # Field density (lines with "key : value" pattern)
    field_pattern_count = len(re.findall(r"[A-Za-z\u0900-\u097F][^:]+:\s*\S", text))
    field_pattern_density = field_pattern_count / max(line_count, 1)

    # Numeric row density (lines that are mostly numbers/amounts)
    numeric_lines = sum(1 for l in lines if sum(c.isdigit() or c in ",.₹/- " for c in l) / max(len(l),1) > 0.5)
    numeric_row_density = numeric_lines / max(line_count, 1)

    # Layout hints from page analysis
    dna = page_analysis.get("dna", {}) if isinstance(page_analysis, dict) else {}

    return {
        "word_count":            word_count,
        "line_count":            line_count,
        "devanagari_ratio":      round(devanagari_ratio, 3),
        "latin_ratio":           round(latin_ratio, 3),
        "numeric_ratio":         round(numeric_ratio, 3),
        "table_density":         round(table_density, 3),
        "table_row_count":       table_rows,
        "table_block_count":     len(table_blocks),
        "currency_present":      currency_present,
        "has_currency_amounts":  has_currency_amt,
        "field_pattern_density": round(field_pattern_density, 3),
        "numeric_row_density":   round(numeric_row_density, 3),
        "has_12digit":           has_12digit,
        "has_pan_pattern":       has_pan,
        "has_gstin":             has_gstin,
        "has_ifsc":              has_ifsc,
        "has_mrz":               has_mrz,
        "column_count":          dna.get("column_count", 1),
        "has_dense_rows":        dna.get("has_dense_rows", False),
        "has_grid_lines":        dna.get("has_grid_lines", False),
    }


def _score_signature(
    text:     str,
    features: Dict,
    doc_key:  str,
) -> float:
    """Score a single document signature against features."""
    patterns = _PATTERNS.get(doc_key, [])
    if not patterns:
        return 0.0

    score   = 0.0
    max_pos = sum(w for _, w, _ in patterns)

    for name, weight, pattern in patterns:
        if pattern.search(text):
            score += weight

    return min(0.95, score / max(max_pos, 1.0))


def match_document_type(
    features: Dict,
    hint:     Optional[str] = None,
    text:     str = "",
) -> Dict:
    """
    Match document type from features.
    Returns soft signals — never hard classification.
    """
    if not text and not features:
        return {
            "doc_type": "unknown", "confidence": 0.0,
            "scores": {}, "features": features, "soft_hints": [],
        }

    scores: Dict[str, float] = {}
    for doc_key in _PATTERNS:
        scores[doc_key] = _score_signature(text, features, doc_key)

    # Feature-based boosts (independent of text patterns)
    if features.get("has_12digit"):
        scores["aadhaar"] = min(0.95, scores.get("aadhaar", 0) + 0.20)
    if features.get("has_pan_pattern"):
        scores["pan"]     = min(0.95, scores.get("pan", 0) + 0.25)
    if features.get("has_gstin"):
        scores["invoice"] = min(0.95, scores.get("invoice", 0) + 0.20)
    if features.get("has_ifsc"):
        scores["bank_statement"] = min(0.95, scores.get("bank_statement", 0) + 0.15)
    if features.get("has_mrz"):
        scores["passport"] = min(0.95, scores.get("passport", 0) + 0.30)
    if features.get("table_density", 0) > 0.4 and features.get("numeric_row_density", 0) > 0.3:
        scores["bank_statement"] = min(0.95, scores.get("bank_statement", 0) + 0.10)
        scores["marksheet"]      = min(0.95, scores.get("marksheet", 0) + 0.08)
    if features.get("devanagari_ratio", 0) > 0.30:
        scores["ration_card"]    = min(0.95, scores.get("ration_card", 0) + 0.08)
        scores["government_doc"] = min(0.95, scores.get("government_doc", 0) + 0.05)

    # Hint boost (caller provides a hint from earlier analysis)
    if hint and hint in scores:
        scores[hint] = min(0.95, scores[hint] + 0.10)

    # Best match
    best_type = max(scores, key=scores.get) if scores else "unknown"
    best_conf = scores.get(best_type, 0.0)

    if best_conf < 0.08:
        best_type = "unknown"
        best_conf = 0.0

    # Soft hints
    soft_hints: List[str] = []
    if features.get("has_12digit"):          soft_hints.append("12-digit ID")
    if features.get("has_pan_pattern"):      soft_hints.append("PAN format")
    if features.get("has_gstin"):            soft_hints.append("GSTIN present")
    if features.get("currency_present"):     soft_hints.append("currency markers")
    if features.get("table_density", 0) > 0.3: soft_hints.append(f"{features['table_block_count']} tables")
    if features.get("devanagari_ratio", 0) > 0.2: soft_hints.append("Devanagari script")
    if features.get("field_pattern_density", 0) > 0.3: soft_hints.append("form fields")

    logger.debug(
        "[doc_dna] Type=%s conf=%.2f scores=%s",
        best_type, best_conf,
        {k: f"{v:.2f}" for k, v in sorted(scores.items(), key=lambda x: -x[1])[:3]},
    )

    return {
        "doc_type":   best_type,
        "confidence": round(best_conf, 3),
        "scores":     {k: round(v, 3) for k, v in scores.items()},
        "features":   features,
        "soft_hints": soft_hints[:5],
    }


def get_reconstruction_hints(doc_type: str, confidence: float) -> Dict:
    """
    Return reconstruction hints for a document type.
    These are used by the pipeline to improve structure reconstruction.
    Low confidence -> conservative hints (no strong assumptions).
    """
    if confidence < 0.15:
        return {
            "expect_tables":       False,
            "expect_form_fields":  False,
            "expect_stamps":       False,
            "expect_handwriting":  False,
            "expect_multilingual": False,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        }

    _HINTS: Dict[str, Dict] = {
        "aadhaar": {
            "expect_tables":       False,
            "expect_form_fields":  True,
            "expect_stamps":       True,
            "expect_handwriting":  False,
            "expect_multilingual": True,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        },
        "pan": {
            "expect_tables":       False,
            "expect_form_fields":  True,
            "expect_stamps":       False,
            "expect_handwriting":  False,
            "expect_multilingual": True,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        },
        "bank_statement": {
            "expect_tables":       True,
            "expect_form_fields":  True,
            "expect_stamps":       False,
            "expect_handwriting":  False,
            "expect_multilingual": False,
            "numeric_alignment":   True,
            "column_count_hint":   1,
        },
        "invoice": {
            "expect_tables":       True,
            "expect_form_fields":  True,
            "expect_stamps":       True,
            "expect_handwriting":  False,
            "expect_multilingual": False,
            "numeric_alignment":   True,
            "column_count_hint":   1,
        },
        "marksheet": {
            "expect_tables":       True,
            "expect_form_fields":  True,
            "expect_stamps":       True,
            "expect_handwriting":  False,
            "expect_multilingual": True,
            "numeric_alignment":   True,
            "column_count_hint":   1,
        },
        "ration_card": {
            "expect_tables":       False,
            "expect_form_fields":  True,
            "expect_stamps":       True,
            "expect_handwriting":  True,
            "expect_multilingual": True,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        },
        "government_doc": {
            "expect_tables":       False,
            "expect_form_fields":  True,
            "expect_stamps":       True,
            "expect_handwriting":  False,
            "expect_multilingual": True,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        },
        "passport": {
            "expect_tables":       False,
            "expect_form_fields":  True,
            "expect_stamps":       False,
            "expect_handwriting":  False,
            "expect_multilingual": False,
            "numeric_alignment":   False,
            "column_count_hint":   1,
        },
    }

    hints = _HINTS.get(doc_type, {
        "expect_tables":       False,
        "expect_form_fields":  False,
        "expect_stamps":       False,
        "expect_handwriting":  False,
        "expect_multilingual": False,
        "numeric_alignment":   False,
        "column_count_hint":   1,
    })

    # Scale back strong hints for low-confidence matches
    if confidence < 0.30:
        hints = {k: (v if isinstance(v, int) else False) for k, v in hints.items()}

    return hints
