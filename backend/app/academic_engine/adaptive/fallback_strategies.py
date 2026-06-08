"""
academic_engine/adaptive/fallback_strategies.py
-------------------------------------------------
Spatial fallback strategies when primary anchor detection fails.

Strategies (escalation order):
  1. same_row_numerics  — numeric on same row as any label
  2. rightmost_numeric  — rightmost numeric in zone (% usually right-aligned)
  3. largest_number     — largest-font numeric blob (height heuristic)
  4. dense_text_row     — row with highest digit density
  5. full_zone_regex    — regex scan over concatenated zone text
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.logger import logger
from app.academic_engine.layout_v2.spatial_relationships import (
    same_row, group_into_rows,
)

_PCT_RE  = re.compile(r'\d{1,3}(?:\.\d{1,2})?')
_YEAR_RE = re.compile(r'20\d{2}')
NOISE = {"subject","code","marks","obtained","maximum","theory","practical",
         "internal","external","written","total","grand"}


@dataclass
class FallbackResult:
    strategy:   str
    raw_text:   str
    confidence: float = 0.3

    @property
    def found(self) -> bool:
        return bool(self.raw_text and self.raw_text.strip())


def _numeric(text: str) -> bool:
    return bool(_PCT_RE.fullmatch(text.strip('%')))

def _year(text: str) -> bool:
    return bool(_YEAR_RE.fullmatch(text.strip()))

def _valid_pct(val_str: str) -> bool:
    try:
        v = float(val_str)
        return 0.0 < v <= 100.0
    except ValueError:
        return False


def _strat_same_row(words: List[Dict], _img=None) -> FallbackResult:
    labels   = [w for w in words if not _numeric(w["text"]) and not _year(w["text"])
                and w["text"].lower() not in NOISE]
    numerics = [w for w in words if _numeric(w["text"]) and not _year(w["text"])]
    hits = []
    for lbl in labels:
        for num in numerics:
            if same_row(lbl["bbox"], num["bbox"], tolerance_px=20):
                val = num["text"].strip('%')
                if _valid_pct(val):
                    hits.append((num.get("conf", 50) / 100.0, val))
    if hits:
        c, v = max(hits, key=lambda x: x[0])
        return FallbackResult("same_row_numerics", v, c)
    return FallbackResult("same_row_numerics", "")


def _strat_rightmost(words: List[Dict], _img=None) -> FallbackResult:
    nums = [w for w in words if _numeric(w["text"]) and not _year(w["text"])]
    if not nums:
        return FallbackResult("rightmost_numeric", "")
    best = max(nums, key=lambda w: w["bbox"][0] + w["bbox"][2])
    val = best["text"].strip('%')
    if _valid_pct(val):
        return FallbackResult("rightmost_numeric", val, best.get("conf", 50) / 100.0)
    return FallbackResult("rightmost_numeric", "")


def _strat_largest_font(words: List[Dict], _img=None) -> FallbackResult:
    nums = [w for w in words if _numeric(w["text"]) and not _year(w["text"])]
    if not nums:
        return FallbackResult("largest_number", "")
    biggest = max(nums, key=lambda w: w["bbox"][3])
    val = biggest["text"].strip('%')
    if _valid_pct(val):
        return FallbackResult("largest_number", val, biggest.get("conf", 50) / 100.0)
    return FallbackResult("largest_number", "")


def _strat_dense_row(words: List[Dict], _img=None) -> FallbackResult:
    if not words:
        return FallbackResult("dense_text_row", "")
    rows = group_into_rows([w["bbox"] for w in words], row_gap_px=15)
    best_score, best_words = -1, []
    for row_bboxes in rows:
        row_ws = [
            w for w in words
            if any(abs((w["bbox"][1]+w["bbox"][3]//2)-(rb[1]+rb[3]//2)) < 20
                   for rb in row_bboxes)
        ]
        score = sum(sum(1 for c in w["text"] if c.isdigit()) for w in row_ws)
        if score > best_score:
            best_score, best_words = score, row_ws
    row_text = " ".join(w["text"] for w in best_words)
    m = _PCT_RE.search(row_text)
    if m and _valid_pct(m.group()):
        return FallbackResult("dense_text_row", m.group(), 0.35)
    return FallbackResult("dense_text_row", "")


def _strat_full_regex(words: List[Dict], _img=None) -> FallbackResult:
    full = " ".join(w["text"] for w in words)
    for m in re.findall(r'\d{1,3}\.\d{1,2}', full):
        if _valid_pct(m) and float(m) >= 20.0:
            return FallbackResult("full_zone_regex", m, 0.3)
    return FallbackResult("full_zone_regex", "")


_STRATEGIES = [_strat_same_row, _strat_rightmost, _strat_largest_font,
               _strat_dense_row, _strat_full_regex]


def run_fallback_strategies(
    words: List[Dict],
    zone_image=None,
    min_confidence: float = 0.2,
) -> Optional[FallbackResult]:
    for fn in _STRATEGIES:
        try:
            r = fn(words, zone_image)
            if r.found and r.confidence >= min_confidence:
                logger.info("[fallback] %s → %r conf=%.2f", r.strategy, r.raw_text, r.confidence)
                return r
        except Exception as exc:
            logger.debug("[fallback] %s failed: %s", fn.__name__, exc)
    logger.info("[fallback] All strategies exhausted")
    return None
