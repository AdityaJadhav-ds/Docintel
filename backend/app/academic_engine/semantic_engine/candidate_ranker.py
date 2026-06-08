import re
from .semantic_validators import SemanticValidators


class CandidateRanker:
    """
    Candidate scoring engine — tuned for Maharashtra SSC/HSC marksheets.
    Covers: SSC 1988, SSC 2000, SSC 2020, HSC 2022 (statement + certificate).
    """

    # Words that should NEVER appear in a candidate name
    _NAME_BLACKLIST = {
        'board', 'university', 'examination', 'marksheet', 'institute',
        'school', 'college', 'council', 'certificate', 'education',
        'divisional', 'secondary', 'maharashtra', 'state', 'pune',
        'msbshse', 'kolhapur', 'mumbai', 'nashik', 'science', 'commerce',
        'arts', 'technical', 'higher', 'nita', 'mother',  # mother name labels
    }

    def score_name_candidate(self, text: str) -> float:
        score = 0.0
        t = str(text).strip()

        if not t:
            return -999.0

        words = t.split()

        # ── Positive signals ──────────────────────────────────
        # 2–4 word names are ideal (Indian names: Surname Given Middle)
        if 2 <= len(words) <= 4:
            score += 4.0
        elif len(words) == 1 and len(t) >= 4:
            score += 0.5  # single word can be a name
        elif len(words) > 5:
            score -= 2.0  # too long for a name

        # Title case (new format) or ALL CAPS (old format) both valid
        if t.istitle():
            score += 3.0
        elif t.isupper() and len(words) >= 2:
            score += 2.5

        # All alphabetic (no digits/symbols)
        if t.replace(' ', '').isalpha():
            score += 2.0

        # ── Negative signals ──────────────────────────────────
        # Organisational keyword in name
        t_lower = t.lower()
        if any(b in t_lower for b in self._NAME_BLACKLIST):
            score -= 25.0

        # Digits strongly suggest it's NOT a name
        if any(c.isdigit() for c in t):
            score -= 15.0

        # Very short (probably a label abbreviation)
        if len(t) < 4:
            score -= 5.0

        # Contains slashes or special chars
        if re.search(r'[/\\|@#$%^&*(){}\[\]]', t):
            score -= 10.0

        return score

    def score_percentage_candidate(self, text: str, node: dict, graph) -> float:
        score = 0.0
        t = str(text).strip()

        # ── Hard reject: serial/barcode numbers ──────────────
        if re.search(r'[A-Z]\d{6,}', t, re.IGNORECASE):
            return -100.0
        if re.search(r'\d{8,}', t):
            return -100.0

        # ── Hard reject: contains alphabetic words (merged rows) ──
        # e.g. "71 33 PASS" or "75.17 FOUR HUNDRED" — not a clean percentage
        words = t.split()
        alpha_words = [w for w in words if re.match(r'^[A-Za-z]{3,}$', w)]
        if alpha_words:
            score -= 20.0  # Heavily penalise — won't pass

        # ── Valid percentage format ───────────────────────────
        num = SemanticValidators.extract_percentage_number(t)
        if num is None:
            return -50.0

        score += 5.0  # valid range

        # Decimal strongly preferred (71.33, 75.17, 37.28, 82.40)
        if re.search(r'\d\.\d', t):
            score += 4.0

        # Single clean token (not a multi-number row)
        if len(words) == 1:
            score += 3.0
        elif len(words) == 2 and all(re.match(r'^\d+$', w) for w in words):
            score += 1.0  # space-split decimal like "71 33"

        # Typical school percentage is > 30%
        if num >= 30.0:
            score += 1.0

        # Contains % symbol
        if '%' in t:
            score += 3.0

        # ── Context: left/above neighbour has "percentage" label ──
        left_id = node['relationships'].get('nearest_left')
        if left_id:
            left = graph.get_node(left_id)
            if left and re.search(r'percent|%', left['text'], re.IGNORECASE):
                score += 8.0

        for n in graph.nodes:
            if n['relationships'].get('nearest_below') == node['id']:
                if re.search(r'percent|%', n['text'], re.IGNORECASE):
                    score += 6.0
                    break

        return score
