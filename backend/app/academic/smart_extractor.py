"""
app/academic/smart_extractor.py — Anchor-Based Line-Context Extraction Engine
==============================================================================
Core strategy: ANCHOR LINE → VALUE LINE (next line below)
Not full-text regex — line-by-line key-value awareness.
"""

from __future__ import annotations
import re
from typing import Optional, List, Dict, Any
from app.core.logger import logger
from app.academic.academic_score_priority import apply_score_priority, get_primary_score_label


# ── Blacklists ────────────────────────────────────────────────────────────────

_SUBJECT_WORDS = {
    "english", "physics", "chemistry", "biology", "mathematics", "maths",
    "geography", "science", "history", "civics", "economics", "computer",
    "marathi", "hindi", "sanskrit", "french", "german", "urdu", "gujarati",
    "drawing", "arts", "commerce", "technology", "information", "social",
    "environment", "health", "physical", "education", "defence", "vocational",
    "semester", "grade", "percentage", "board", "university", "result",
    "total", "marks", "obtained", "statement", "secondary", "higher",
    "primary", "certificate", "examination", "district", "division",
    "kolhapur", "pune", "mumbai", "nashik", "aurangabad", "nagpur",
    "maharashtra", "cbse", "icse", "divisional", "secretary", "principal",
}

# Lines that are still labels — NOT name values
_NAME_SKIP_RE = re.compile(
    r"surname\s+first|"
    r"\(surname|"
    r"mother.?s?\s+name|"
    r"आईचे\s+नाव|"
    r"candidate.?s?\s+(?:full\s+)?name|"
    r"student.?s?\s+name|"
    r"full\s+name\s*$|"
    r"name\s+of\s+(?:the\s+)?(?:candidate|student)|"
    r"father.?s?\s+name|"
    r"^\s*name\s*$",
    re.IGNORECASE,
)

# Lines to skip entirely (noisy table headers)
_SKIP_TABLE_LINE_RE = re.compile(
    r"\b(english|physics|chemistry|biology|mathematics|geography|"
    r"marathi|hindi|science|technology|social|subject\s+code|"
    r"in\s+words|in\s+figures|medium|max\.?\s*marks)\b",
    re.IGNORECASE,
)

# OCR garbage symbols that appear as leading noise on name lines
_NAME_LEADING_GARBAGE_RE = re.compile(r"^[^A-Za-z\u0900-\u097F]+")
_NAME_GARBAGE_SYMBOLS_RE = re.compile(r"[{}\[\]|:;_=+~`<>@#^*\\]")


def _strip_name_garbage(raw: str) -> str:
    """
    Remove OCR noise symbols from a candidate name line.
    Examples:
      '} Jadhav Aditya Bhagvan'  → 'Jadhav Aditya Bhagvan'
      '| KUMAR RAHUL SINGH'      → 'KUMAR RAHUL SINGH'
    """
    cleaned = _NAME_GARBAGE_SYMBOLS_RE.sub(" ", raw)
    cleaned = _NAME_LEADING_GARBAGE_RE.sub("", cleaned)
    return " ".join(cleaned.split())


# ── Name validation ────────────────────────────────────────────────────────────

def _is_valid_name(s: str) -> bool:
    s = s.strip()
    words = s.split()
    if len(words) < 2 or len(s) < 6 or len(s) > 60:
        return False
    low_words = [w.lower() for w in words]
    if any(w in _SUBJECT_WORDS for w in low_words):
        return False
    if _NAME_SKIP_RE.search(s):
        return False
    alpha_ratio = sum(c.isalpha() or c == " " for c in s) / len(s)
    if alpha_ratio < 0.85:
        return False
    if re.search(r"\d{3,}", s):
        return False
    if re.search(r"board|university|college|institute|school|vidyalaya|divisional", s, re.I):
        return False
    return True


# ── Line splitting ────────────────────────────────────────────────────────────

def _to_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines()]


# ── Document classification ───────────────────────────────────────────────────

def _classify(text: str, hint: Optional[str] = None) -> str:
    if hint in ("ssc", "hsc", "degree"):
        return hint

    low = text.lower()

    # Hard overrides
    if re.search(r"statement\s+of\s+grades?|cgpa|sgpa", low):
        return "degree"
    if re.search(r"bachelor|master|b\.tech|b\.e\b|b\.sc|mba|bca|mca|prn\b", low):
        return "degree"

    ssc = 0
    hsc = 0
    lines = _to_lines(text)
    header = "\n".join(lines[:25]).lower()

    if re.search(r"secondary\s+school\s+certificate|माध्यमिक\s+शालान्त|\bssc\b", header):
        ssc += 10
    if re.search(r"higher\s+secondary\s+certificate|उच्च\s*माध्यमिक|\bhsc\b", header):
        hsc += 10
    if re.search(r"class\s*(x\b|10|10th)", header):
        ssc += 6
    if re.search(r"class\s*(xii\b|12|12th)", header):
        hsc += 6
    if re.search(r"\bscience\b|\bcommerce\b|\barts\b|\bstream\b", header):
        hsc += 4
    if re.search(r"march[- ]?20\d{2}|march[- ]?\d{2}\b", header):
        ssc += 2; hsc += 2  # both use march dates

    if ssc == 0 and hsc == 0:
        if re.search(r"10th", low): return "ssc"
        if re.search(r"12th", low): return "hsc"
        return "unknown"

    return "ssc" if ssc >= hsc else "hsc"


# ── Anchor → next-line extraction (NAME) ─────────────────────────────────────

_NAME_ANCHOR_RE = re.compile(
    r"candidate.{0,25}full\s+name|"
    r"candidate.{0,10}name|"
    r"student.{0,10}name|"
    r"name\s+of\s+(?:the\s+)?(?:candidate|student)|"
    r"उमेदवाराचे\s+संपूर्ण\s+नाव|"
    r"this\s+is\s+to\s+certify\s+that",
    re.IGNORECASE,
)


def _extract_name(lines: List[str]) -> Optional[str]:
    for i, line in enumerate(lines):
        if _NAME_ANCHOR_RE.search(line):
            # Look at next 4 lines for the actual name value
            for j in range(i + 1, min(i + 5, len(lines))):
                candidate = lines[j].strip()
                if not candidate:
                    continue
                # Skip if this is still a label line
                if _NAME_SKIP_RE.search(candidate):
                    continue
                # Skip table noise
                if _SKIP_TABLE_LINE_RE.search(candidate):
                    continue
                # Strip OCR garbage symbols before validation
                candidate_clean = _strip_name_garbage(candidate)
                if _is_valid_name(candidate_clean):
                    # Clean up — take only the name part before any slash
                    name = re.split(r"/", candidate_clean)[0].strip()
                    # Final leading-garbage strip in case slash produced a fragment
                    name = _NAME_LEADING_GARBAGE_RE.sub("", name).strip()
                    return name.title() if name else None
    return None


# ── Inline-value extraction (same line as anchor) ────────────────────────────

def _extract_inline_number(line: str, min_val: float, max_val: float) -> Optional[float]:
    """Extract first valid number from a line within [min_val, max_val]."""
    nums = re.findall(r"\b(\d{1,4}(?:\.\d{1,2})?)\b", line)
    for n in nums:
        try:
            v = float(n)
            if min_val <= v <= max_val:
                return v
        except ValueError:
            pass
    return None


def _extract_percentage(lines: List[str]) -> Optional[float]:
    for line in reversed(lines):  # bottom-up priority
        low = line.lower()
        if re.search(r"percentage|टक्केवारी|%|percent", low):
            # Skip pure label lines that have no numbers
            v = _extract_inline_number(line, 10.0, 100.0)
            if v:
                return round(v, 2)
    return None


def _extract_total_obtained(lines: List[str]) -> tuple[Optional[float], Optional[float]]:
    """Returns (obtained, total)."""
    total    = None
    obtained = None

    for line in reversed(lines):
        low = line.lower()
        if not re.search(r"total\s+marks?|एकूण\s+गुण|grand\s+total|aggregate\s+marks?", low):
            continue
        # Ignore subject table lines
        if _SKIP_TABLE_LINE_RE.search(line):
            continue

        nums = re.findall(r"\b(\d{2,4})\b", line)
        # Clean $ / £ prefixed numbers (Maharashtra quirk like $407)
        raw_nums = re.findall(r"[\$£]?(\d{2,4})(?:[+]\d+)?", line)
        all_nums = []
        for n in raw_nums:
            try:
                v = int(n)
                if 50 <= v <= 2000:
                    all_nums.append(v)
            except ValueError:
                pass

        if len(all_nums) >= 2:
            # Heuristic: larger = total, smaller = obtained
            all_nums_sorted = sorted(set(all_nums), reverse=True)
            total   = float(all_nums_sorted[0])
            # obtained is the next number that's <= total
            for v in all_nums_sorted[1:]:
                if v <= total:
                    obtained = float(v)
                    break
        elif len(all_nums) == 1:
            total = float(all_nums[0])
        break  # use first matching line from bottom

    # Validate
    if obtained and total and obtained > total:
        obtained = None

    return obtained, total


def _extract_result(lines: List[str]) -> Optional[str]:
    for line in reversed(lines):
        low = line.lower()
        if re.search(r"result|निकाल", low):
            if re.search(r"\bpass\b|\bpassed\b", low):
                return "PASS"
            if re.search(r"\bfail\b|\bfailed\b", low):
                return "FAIL"
    # Scan whole text for result keywords
    full = "\n".join(lines).lower()
    if re.search(r"\bpassed\b", full):
        return "PASS"
    if re.search(r"\bfailed\b", full):
        return "FAIL"
    return None


def _extract_grade(lines: List[str]) -> Optional[str]:
    full = "\n".join(lines).lower()
    priority = [
        (r"first\s+class\s+with\s+distinction", "First Class with Distinction"),
        (r"\bi[-\s]?dist\b",                     "Distinction"),
        (r"\bdistinction\b",                      "Distinction"),
        (r"first\s+class",                        "First Class"),
        (r"second\s+class",                       "Second Class"),
        (r"pass\s+class",                         "Pass Class"),
        (r"\boutstanding\b",                       "Outstanding"),
        (r"\bexcellent\b",                         "Excellent"),
    ]
    for pat, label in priority:
        if re.search(pat, full):
            return label
    return None


def _extract_year(lines: List[str]) -> Optional[int]:
    for line in lines[:25]:  # header region
        m = re.search(
            r"(?:march|october|november|july|june|february|april)"
            r"[-,\s]+(?:20)?(\d{2})\b",
            line, re.IGNORECASE,
        )
        if m:
            yr = int(m.group(1))
            yr = 2000 + yr if yr < 100 else yr
            if 2000 <= yr <= 2030:
                return yr
    # Fallback: first 4-digit year in header
    header = "\n".join(lines[:30])
    for m in re.finditer(r"\b(20[0-2]\d)\b", header):
        yr = int(m.group(1))
        if 2000 <= yr <= 2030:
            return yr
    return None


def _extract_board(text: str, doc_type: str) -> Optional[str]:
    low = text.lower()
    patterns = [
        (r"maharashtra\s+state\s+board",  "Maharashtra State Board"),
        (r"msbshse|msbsh",                "Maharashtra State Board"),
        (r"cbse|central\s+board",         "CBSE"),
        (r"icse|cisce",                   "ICSE"),
        (r"shivaji\s+university",         "Shivaji University, Kolhapur"),
        (r"savitribai\s+phule",           "Savitribai Phule Pune University"),
        (r"mumbai\s+university",          "University of Mumbai"),
        (r"nagpur\s+university",          "Nagpur University"),
    ]
    for pat, label in patterns:
        if re.search(pat, low):
            return label
    return None


def _extract_cgpa(text: str) -> Optional[float]:
    m = re.search(r"cgpa\s*[:\-]?\s*(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        if 0 < v <= 10:
            return round(v, 2)
    return None


def _field_confidence(data: Dict) -> float:
    critical = ["candidate_name", "percentage", "passing_year"]
    present  = sum(1 for f in critical if data.get(f))
    bonus    = sum(0.1 for f in ["obtained_marks", "total_marks", "board", "university", "result"] if data.get(f))
    return round(min(present / 3 * 0.7 + bonus, 1.0), 3)


# ── Master entry point ────────────────────────────────────────────────────────

def smart_extract(raw_text: str, doc_type_hint: Optional[str] = None) -> Dict[str, Any]:
    if not raw_text or len(raw_text.strip()) < 40:
        return {"document_type": "unknown"}

    lines    = _to_lines(raw_text)
    doc_type = _classify(raw_text, doc_type_hint)

    name              = _extract_name(lines)
    percentage        = _extract_percentage(lines)
    obtained, total   = _extract_total_obtained(lines)
    result            = _extract_result(lines)
    grade             = _extract_grade(lines)
    year              = _extract_year(lines)
    board             = _extract_board(raw_text, doc_type)
    cgpa              = _extract_cgpa(raw_text) if doc_type == "degree" else None

    # Compute percentage from marks if not found
    if percentage is None and obtained and total and total > 0:
        calc = (obtained / total) * 100
        if 10 <= calc <= 100:
            percentage = round(calc, 2)

    out: Dict[str, Any] = {
        "document_type":  doc_type,
        "candidate_name": name,
        "percentage":     percentage,
        "obtained_marks": int(obtained) if obtained is not None else None,
        "total_marks":    int(total)    if total    is not None else None,
        "grade":          grade,
        "result":         result,
        "passing_year":   year,
    }

    if doc_type == "degree":
        out["university"] = board
        out["cgpa"]       = cgpa
    else:
        out["board"] = board

    # Strip Nones for clean output
    out = {k: v for k, v in out.items() if v is not None}
    out["document_type"] = doc_type

    # ── Apply score priority: only show the highest-value final score ─────────
    out = apply_score_priority(out)
    primary = get_primary_score_label(out)

    logger.info(
        "[smart_extractor] type=%s name=%s primary_score=%s pct=%s cgpa=%s marks=%s/%s year=%s",
        doc_type, name, primary,
        out.get("percentage"), out.get("cgpa"),
        out.get("obtained_marks"), out.get("total_marks"), year,
    )

    return out
