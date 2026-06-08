"""
academic_engine/adaptive/roi_retry_engine.py
=============================================
Self-Healing ROI Extraction Orchestrator.

This is the TOP-LEVEL adaptive engine. It coordinates all other
adaptive modules to achieve maximum extraction reliability.

For each target field (percentage, cgpa, result, candidate_name):

  ATTEMPT 1 — Primary ROI
    Run roi_optimizer (multi-preprocessing × multi-engine OCR)
    on the anchor-derived crop from SummaryLocator.

  ATTEMPT 2 — Crop Escalation
    If attempt 1 yields no valid result:
    Generate alternate crop variants via AdaptiveCropper.
    Run roi_optimizer on each crop variant in priority order.
    Stop at first valid result.

  ATTEMPT 3 — Spatial Fallback
    If all crop variants fail:
    Run spatial fallback strategies (same-row, rightmost, dense-row, etc.)
    on the full word-level OCR data from the zone.

  ATTEMPT 4 — Confidence Recovery
    If a near-miss value was found (structurally close to valid):
    Apply OCR text repair (decimal insertion, char substitution, etc.)
    Re-validate the repaired value.

  FAILURE REASONING
    If all 4 attempts fail:
    Record the EXACT failure stage and reason for debug visualization.

Output:
  AdaptiveExtractionResult with:
    - value (str | None)
    - confidence (float)
    - strategy_used (str)
    - attempts (list of AttemptRecord for debug)
    - failure_reason (str | None)
    - recovered (bool)

Auto-Tuning Metrics:
  RetryMetrics tracks per-session statistics:
    - total calls per field
    - attempt distributions
    - recovery rates
    - average confidence
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logger import logger
from app.academic_engine.adaptive.adaptive_cropper import (
    generate_crop_variants, CropVariant,
)
from app.academic_engine.adaptive.roi_optimizer import (
    optimize_roi_ocr, OcrEnsembleResult,
)
from app.academic_engine.adaptive.fallback_strategies import (
    run_fallback_strategies,
)
from app.academic_engine.adaptive.confidence_recovery import (
    recover_percentage, recover_cgpa, recover_result, recover_name,
)
from app.academic_engine.adaptive.candidate_name_ranker import (
    rank_name_candidates, extract_best_name,
)


# ── Attempt record (debug) ─────────────────────────────────────────────────────

@dataclass
class AttemptRecord:
    attempt_num:    int
    strategy:       str          # "primary_roi" | "crop_variant:expand_h" | "fallback:same_row" | "recovery"
    text:           str
    confidence:     float
    valid:          bool
    preprocessing:  str = ""
    engine:         str = ""
    failure_reason: str = ""
    elapsed_ms:     float = 0.0

    def to_dict(self) -> Dict:
        return {
            "attempt":      self.attempt_num,
            "strategy":     self.strategy,
            "text":         self.text,
            "confidence":   round(self.confidence, 3),
            "valid":        self.valid,
            "preprocessing": self.preprocessing,
            "engine":       self.engine,
            "failure":      self.failure_reason,
        }


# ── Final result ───────────────────────────────────────────────────────────────

@dataclass
class AdaptiveExtractionResult:
    field:          str
    value:          Optional[str]    = None
    confidence:     float            = 0.0
    strategy_used:  str              = ""
    attempts:       List[AttemptRecord] = field(default_factory=list)
    failure_reason: Optional[str]    = None
    recovered:      bool             = False
    total_attempts: int              = 0
    elapsed_ms:     float            = 0.0

    @property
    def found(self) -> bool:
        return self.value is not None and bool(self.value.strip())

    def to_dict(self) -> Dict:
        return {
            "field":         self.field,
            "value":         self.value,
            "confidence":    round(self.confidence, 3),
            "strategy_used": self.strategy_used,
            "total_attempts": self.total_attempts,
            "recovered":     self.recovered,
            "failure_reason": self.failure_reason,
            "elapsed_ms":    round(self.elapsed_ms, 1),
            "attempts":      [a.to_dict() for a in self.attempts],
        }


# ── Auto-tuning metrics ────────────────────────────────────────────────────────

class RetryMetrics:
    """Session-level statistics for adaptive extraction tuning."""

    def __init__(self):
        self._calls:      Dict[str, int]   = defaultdict(int)
        self._successes:  Dict[str, int]   = defaultdict(int)
        self._recoveries: Dict[str, int]   = defaultdict(int)
        self._attempts:   Dict[str, list]  = defaultdict(list)
        self._conf_sum:   Dict[str, float] = defaultdict(float)

    def record(self, result: AdaptiveExtractionResult) -> None:
        f = result.field
        self._calls[f]     += 1
        self._attempts[f].append(result.total_attempts)
        if result.found:
            self._successes[f] += 1
            self._conf_sum[f]  += result.confidence
        if result.recovered:
            self._recoveries[f] += 1

    def summary(self) -> Dict:
        out = {}
        for f in self._calls:
            n = self._calls[f]
            s = self._successes[f]
            atts = self._attempts[f]
            out[f] = {
                "total_calls":    n,
                "success_rate":   round(s / n, 3) if n else 0,
                "recovery_rate":  round(self._recoveries[f] / n, 3) if n else 0,
                "avg_attempts":   round(sum(atts) / len(atts), 2) if atts else 0,
                "avg_confidence": round(self._conf_sum[f] / s, 3) if s else 0,
            }
        return out

    def log_summary(self) -> None:
        summary = self.summary()
        for f, stats in summary.items():
            logger.info("[retry_metrics] %-15s %s", f, stats)


_METRICS = RetryMetrics()


# ── Validators ────────────────────────────────────────────────────────────────

import re

def _valid_pct(text: str) -> Optional[str]:
    m = re.search(r'\d{1,3}(?:\.\d{1,2})?', text)
    if m:
        try:
            v = float(m.group())
            if 0.0 < v <= 100.0:
                return str(round(v, 2))
        except ValueError:
            pass
    return None


def _valid_cgpa(text: str) -> Optional[str]:
    m = re.search(r'\d{1,2}(?:\.\d{1,2})?', text)
    if m:
        try:
            v = float(m.group())
            if 0.0 < v <= 10.0:
                return str(round(v, 2))
        except ValueError:
            pass
    return None


_RESULT_KEYWORDS = {"PASS","FAIL","DISTINCTION","FIRST","SECOND","THIRD",
                    "CLASS","COMPARTMENT","ABSENT","WITHHELD","PASSED","FAILED"}

def _valid_result(text: str) -> Optional[str]:
    clean = re.sub(r'[^A-Za-z\s]', '', text).upper().strip()
    for kw in ["DISTINCTION", "FIRST CLASS", "SECOND CLASS", "THIRD CLASS",
               "PASS", "FAIL", "COMPARTMENT", "ABSENT", "WITHHELD"]:
        if kw in clean:
            return kw
    return None


def _valid_name(text: str) -> Optional[str]:
    clean = re.sub(r'[^A-Za-z\s]', '', text).strip()
    words = clean.split()
    if 2 <= len(words) <= 6 and all(len(w) >= 2 for w in words):
        return " ".join(w.capitalize() for w in words)
    return None


_VALIDATORS = {
    "percentage": _valid_pct,
    "cgpa":       _valid_cgpa,
    "result":     _valid_result,
    "candidate":  _valid_name,
}

_RECOVERY_FNS = {
    "percentage": recover_percentage,
    "cgpa":       recover_cgpa,
    "result":     recover_result,
    "candidate":  recover_name,
}


# ── Main retry engine ─────────────────────────────────────────────────────────

class ROIRetryEngine:
    """
    Adaptive ROI extraction orchestrator with 4-tier retry logic.

    Usage:
        engine = ROIRetryEngine()
        result = engine.extract(
            field="percentage",
            primary_roi=roi_bgr_or_none,
            zone_image=summary_zone_bgr,
            anchor_bbox=(x, y, w, h),
            zone_words=[{text, bbox, conf}, ...],
        )
    """

    def extract(
        self,
        field:        str,
        primary_roi:  Optional[np.ndarray],
        zone_image:   Optional[np.ndarray],
        anchor_bbox:  Optional[tuple] = None,
        zone_words:   Optional[List[Dict]] = None,
    ) -> AdaptiveExtractionResult:
        """
        Run adaptive 4-tier extraction for a single field.

        Args:
            field:        "percentage" | "cgpa" | "result" | "candidate"
            primary_roi:  Primary anchor-derived crop (may be None)
            zone_image:   Full zone BGR image (summary zone)
            anchor_bbox:  (x,y,w,h) bbox of anchor label in zone_image
            zone_words:   Word records from Tesseract data on zone_image

        Returns:
            AdaptiveExtractionResult
        """
        t0      = time.time()
        result  = AdaptiveExtractionResult(field=field)
        attempt = 0
        validator = _VALIDATORS.get(field, lambda t: t.strip() or None)

        # ── ATTEMPT 1: Primary ROI ────────────────────────────────────────────
        if primary_roi is not None and primary_roi.size > 0:
            attempt += 1
            t_a = time.time()
            ens = optimize_roi_ocr(primary_roi, field, use_easyocr=True)
            elapsed_a = (time.time() - t_a) * 1000

            winner_text = ens.text
            validated   = validator(winner_text) if winner_text else None

            rec = AttemptRecord(
                attempt_num    = attempt,
                strategy       = "primary_roi",
                text           = winner_text,
                confidence     = ens.confidence,
                valid          = validated is not None,
                preprocessing  = ens.winner.preprocessing if ens.winner else "",
                engine         = ens.winner.engine if ens.winner else "",
                elapsed_ms     = elapsed_a,
            )
            result.attempts.append(rec)

            if validated:
                result.value    = validated
                result.confidence = ens.confidence
                result.strategy_used = "primary_roi"
                result.total_attempts = attempt
                result.elapsed_ms = (time.time() - t0) * 1000
                _METRICS.record(result)
                logger.info("[retry] field=%-15s ✓ attempt=1 strategy=primary_roi value=%r conf=%.2f",
                            field, validated, ens.confidence)
                return result

        # ── ATTEMPT 2: Crop escalation ────────────────────────────────────────
        if zone_image is not None and zone_image.size > 0:
            crop_variants: List[CropVariant] = generate_crop_variants(
                zone_image, anchor_bbox, field=field
            )
            # Skip "exact" (already tried as primary) and "zone_full" (save for last)
            mid_variants = [v for v in crop_variants
                            if v.strategy not in ("exact",)]

            for variant in mid_variants:
                if variant.image is None or variant.image.size == 0:
                    continue
                attempt += 1
                t_a = time.time()
                ens = optimize_roi_ocr(variant.image, field, use_easyocr=(attempt <= 5))
                elapsed_a = (time.time() - t_a) * 1000

                winner_text = ens.text
                validated   = validator(winner_text) if winner_text else None

                rec = AttemptRecord(
                    attempt_num    = attempt,
                    strategy       = f"crop_variant:{variant.strategy}",
                    text           = winner_text,
                    confidence     = ens.confidence,
                    valid          = validated is not None,
                    preprocessing  = ens.winner.preprocessing if ens.winner else "",
                    engine         = ens.winner.engine if ens.winner else "",
                    elapsed_ms     = elapsed_a,
                )
                result.attempts.append(rec)

                if validated:
                    result.value         = validated
                    result.confidence    = max(ens.confidence * 0.85, 0.4)  # slight discount
                    result.strategy_used = f"crop_variant:{variant.strategy}"
                    result.total_attempts = attempt
                    result.elapsed_ms    = (time.time() - t0) * 1000
                    _METRICS.record(result)
                    logger.info("[retry] field=%-15s ✓ attempt=%d strategy=%s value=%r",
                                field, attempt, variant.strategy, validated)
                    return result

                # Early termination after too many crop attempts
                if attempt >= 6:
                    break

        # ── ATTEMPT 3: Spatial fallback ───────────────────────────────────────
        if zone_words:
            attempt += 1
            t_a = time.time()
            fallback = run_fallback_strategies(zone_words, zone_image)
            elapsed_a = (time.time() - t_a) * 1000

            fb_text     = fallback.raw_text if fallback else ""
            fb_conf     = fallback.confidence if fallback else 0.0
            fb_strategy = fallback.strategy if fallback else "none"
            validated   = validator(fb_text) if fb_text else None

            rec = AttemptRecord(
                attempt_num    = attempt,
                strategy       = f"spatial_fallback:{fb_strategy}",
                text           = fb_text,
                confidence     = fb_conf,
                valid          = validated is not None,
                elapsed_ms     = elapsed_a,
                failure_reason = "" if validated else f"fallback {fb_strategy} invalid: {fb_text!r}",
            )
            result.attempts.append(rec)

            if validated:
                result.value         = validated
                result.confidence    = max(fb_conf * 0.75, 0.3)
                result.strategy_used = f"spatial_fallback:{fb_strategy}"
                result.total_attempts = attempt
                result.elapsed_ms    = (time.time() - t0) * 1000
                _METRICS.record(result)
                logger.info("[retry] field=%-15s ✓ attempt=%d strategy=fallback:%s value=%r",
                            field, attempt, fb_strategy, validated)
                return result

        # ── ATTEMPT 4: Confidence recovery ────────────────────────────────────
        # Find the best near-miss text from all previous attempts
        near_misses = [
            a for a in result.attempts
            if a.text and not a.valid and a.confidence > 0.1
        ]
        if near_misses:
            best_near = max(near_misses, key=lambda a: a.confidence)
            recovery_fn = _RECOVERY_FNS.get(field)
            if recovery_fn:
                attempt += 1
                t_a = time.time()
                repaired, repair_note = recovery_fn(best_near.text)
                elapsed_a = (time.time() - t_a) * 1000

                validated = validator(repaired) if repaired else None

                rec = AttemptRecord(
                    attempt_num    = attempt,
                    strategy       = "confidence_recovery",
                    text           = repaired or "",
                    confidence     = best_near.confidence * 0.7,
                    valid          = validated is not None,
                    elapsed_ms     = elapsed_a,
                    failure_reason = "" if validated else f"recovery failed: {repair_note}",
                )
                result.attempts.append(rec)

                if validated:
                    result.value         = validated
                    result.confidence    = best_near.confidence * 0.7
                    result.strategy_used = "confidence_recovery"
                    result.recovered     = True
                    result.total_attempts = attempt
                    result.elapsed_ms    = (time.time() - t0) * 1000
                    _METRICS.record(result)
                    logger.info("[retry] field=%-15s ✓ RECOVERED attempt=%d value=%r note=%s",
                                field, attempt, validated, repair_note)
                    return result

        # ── FAILURE — build diagnostic reason ────────────────────────────────
        result.total_attempts = attempt
        result.elapsed_ms     = (time.time() - t0) * 1000

        if attempt == 0:
            result.failure_reason = f"No ROI or zone data available for field '{field}'"
        elif not any(a.text for a in result.attempts):
            result.failure_reason = f"All {attempt} OCR attempts returned empty text"
        else:
            last = result.attempts[-1]
            result.failure_reason = (
                f"Best near-miss: {last.text!r} (conf={last.confidence:.2f}) — "
                f"could not validate as {field}"
            )

        _METRICS.record(result)
        logger.info(
            "[retry] field=%-15s ✗ FAILED after %d attempts — %s",
            field, attempt, result.failure_reason,
        )
        return result

    def get_metrics(self) -> Dict:
        return _METRICS.summary()

    def log_metrics(self) -> None:
        _METRICS.log_summary()


# ── Session-level multi-field extraction ─────────────────────────────────────

_engine = ROIRetryEngine()


def run_adaptive_extraction(
    fields_config: Dict[str, Dict],
) -> Dict[str, AdaptiveExtractionResult]:
    """
    Run adaptive extraction for multiple fields.

    Args:
        fields_config: Dict of field_name → {
            primary_roi: np.ndarray | None,
            zone_image:  np.ndarray | None,
            anchor_bbox: tuple | None,
            zone_words:  list | None,
        }

    Returns:
        Dict of field_name → AdaptiveExtractionResult
    """
    results = {}
    for field_name, cfg in fields_config.items():
        results[field_name] = _engine.extract(
            field        = field_name,
            primary_roi  = cfg.get("primary_roi"),
            zone_image   = cfg.get("zone_image"),
            anchor_bbox  = cfg.get("anchor_bbox"),
            zone_words   = cfg.get("zone_words"),
        )
    _engine.log_metrics()
    return results


def get_adaptive_metrics() -> Dict:
    """Return current session auto-tuning metrics."""
    return _engine.get_metrics()
