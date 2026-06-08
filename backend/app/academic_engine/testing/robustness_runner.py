"""
academic_engine/testing/robustness_runner.py
=============================================
Bulk Robustness Testing Orchestrator.

Runs a set of DegradedVariant images through the full adaptive pipeline
and collects per-variant metrics for benchmarking.

Workflow:
  1. Receive clean image + ground-truth fields
  2. Generate adversarial variants via adversarial_generator
  3. For each variant, call run_layout_intelligence
  4. Compare extracted fields against ground truth
  5. Return RobustnessSession with all metrics

Parallel processing: uses ThreadPoolExecutor for speed.
"""

from __future__ import annotations

import time
import uuid
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logger import logger
from app.academic_engine.testing.adversarial_generator import (
    DegradedVariant, generate_sweep,
)

# ── Per-variant result ────────────────────────────────────────────────────────

@dataclass
class VariantResult:
    variant_name:      str
    transform:         str
    severity:          float

    # Extraction outcome
    extracted:         Dict[str, Optional[str]] = field(default_factory=dict)
    field_correct:     Dict[str, bool]           = field(default_factory=dict)
    field_confidence:  Dict[str, float]          = field(default_factory=dict)

    # Adaptive engine stats
    total_retries:     int   = 0
    recoveries:        int   = 0
    elapsed_ms:        float = 0.0
    engine_used:       str   = ""

    # Failure detail
    failed:            bool  = False
    error_msg:         str   = ""
    failure_reasons:   Dict[str, str] = field(default_factory=dict)

    @property
    def fields_correct(self) -> int:
        return sum(1 for v in self.field_correct.values() if v)

    @property
    def total_fields(self) -> int:
        return len(self.field_correct)

    @property
    def accuracy(self) -> float:
        if self.total_fields == 0:
            return 0.0
        return self.fields_correct / self.total_fields

    def to_dict(self) -> Dict:
        return {
            "variant":         self.variant_name,
            "transform":       self.transform,
            "severity":        round(self.severity, 3),
            "extracted":       self.extracted,
            "field_correct":   self.field_correct,
            "accuracy":        round(self.accuracy, 3),
            "total_retries":   self.total_retries,
            "recoveries":      self.recoveries,
            "elapsed_ms":      round(self.elapsed_ms, 1),
            "failed":          self.failed,
            "error_msg":       self.error_msg,
            "failure_reasons": self.failure_reasons,
        }


# ── Session aggregate ─────────────────────────────────────────────────────────

@dataclass
class RobustnessSession:
    session_id:    str
    ground_truth:  Dict[str, Optional[str]]
    results:       List[VariantResult] = field(default_factory=list)
    elapsed_s:     float = 0.0

    def total_variants(self) -> int:
        return len(self.results)

    def success_count(self) -> int:
        return sum(1 for r in self.results if not r.failed)

    def full_success_count(self) -> int:
        """Variants where ALL tracked fields are correct."""
        return sum(1 for r in self.results if r.accuracy == 1.0 and not r.failed)

    def per_field_accuracy(self) -> Dict[str, float]:
        """For each tracked field, fraction of variants where it was extracted correctly."""
        fields = set(k for r in self.results for k in r.field_correct)
        out = {}
        for f in fields:
            scores = [r.field_correct.get(f, False) for r in self.results
                      if f in r.field_correct]
            out[f] = round(sum(scores) / len(scores), 3) if scores else 0.0
        return out

    def per_transform_accuracy(self) -> Dict[str, float]:
        families: Dict[str, List[float]] = {}
        for r in self.results:
            families.setdefault(r.transform, []).append(r.accuracy)
        return {k: round(sum(v) / len(v), 3) for k, v in families.items()}

    def avg_retries(self) -> float:
        retries = [r.total_retries for r in self.results]
        return round(sum(retries) / len(retries), 2) if retries else 0.0

    def recovery_rate(self) -> float:
        total_recoveries = sum(r.recoveries for r in self.results)
        total_attempts   = sum(r.total_retries for r in self.results)
        return round(total_recoveries / total_attempts, 3) if total_attempts > 0 else 0.0

    def summary(self) -> Dict:
        return {
            "session_id":          self.session_id,
            "total_variants":      self.total_variants(),
            "success_rate":        round(self.success_count() / max(self.total_variants(), 1), 3),
            "full_accuracy_rate":  round(self.full_success_count() / max(self.total_variants(), 1), 3),
            "per_field_accuracy":  self.per_field_accuracy(),
            "per_transform_accuracy": self.per_transform_accuracy(),
            "avg_retries":         self.avg_retries(),
            "recovery_rate":       self.recovery_rate(),
            "elapsed_s":           round(self.elapsed_s, 1),
        }


# ── Field comparison ──────────────────────────────────────────────────────────

_NUMERIC_FIELDS = {"percentage", "cgpa"}
_NUMERIC_TOLERANCE = 1.0    # within 1.0 unit considered correct


def _compare_field(extracted: Optional[str], ground_truth: Optional[str], field_name: str) -> bool:
    """Return True if extraction matches ground truth."""
    if ground_truth is None:
        return True   # no ground truth = can't judge

    if extracted is None:
        return False

    # Numeric comparison with tolerance
    if field_name in _NUMERIC_FIELDS:
        try:
            ev = float(extracted)
            gv = float(ground_truth)
            return abs(ev - gv) <= _NUMERIC_TOLERANCE
        except (ValueError, TypeError):
            pass

    # Text: case-insensitive stripped comparison
    return extracted.strip().upper() == ground_truth.strip().upper()


# ── Pipeline call (isolated per variant) ─────────────────────────────────────

def _run_pipeline_on_variant(
    variant:     DegradedVariant,
    truth:       Dict[str, Optional[str]],
    session_id:  str,
) -> VariantResult:
    """Run one variant through the full adaptive pipeline."""
    result = VariantResult(
        variant_name=variant.name,
        transform=variant.transform,
        severity=variant.severity,
    )
    t0 = time.time()

    try:
        from app.academic_engine.layout_v2.layout_intelligence_pipeline import (
            run_layout_intelligence,
        )
        sub_session = f"{session_id}_{variant.name[:20]}"
        out = run_layout_intelligence(
            image=variant.image,
            session_id=sub_session,
            debug=False,    # skip image I/O during bulk testing
        )

        meta = out.get("_layout_meta", {})

        # Collect extracted values
        target_fields = ["candidate_name", "percentage", "cgpa", "result", "grade_class"]
        for f in target_fields:
            val = out.get(f)
            result.extracted[f] = val
            if f in truth:
                result.field_correct[f] = _compare_field(val, truth[f], f)

        # Adaptive stats
        adp_results = meta.get("adaptive_results", {})
        for fname, ar in adp_results.items():
            if isinstance(ar, dict):
                result.total_retries += ar.get("total_attempts", 0)
                if ar.get("recovered"):
                    result.recoveries += 1

        result.failure_reasons = meta.get("failure_reasons", {})
        result.engine_used     = meta.get("ocr_engines", [""])[0] if meta.get("ocr_engines") else ""

    except Exception as exc:
        result.failed    = True
        result.error_msg = f"{type(exc).__name__}: {exc}"
        logger.warning("[robustness_runner] variant=%s FAILED: %s", variant.name, exc)

    result.elapsed_ms = (time.time() - t0) * 1000
    return result


# ── Main runner ───────────────────────────────────────────────────────────────

def run_robustness_test(
    clean_image:   np.ndarray,
    ground_truth:  Dict[str, Optional[str]],
    transforms:    Optional[List[str]] = None,
    max_variants:  int = 60,
    max_workers:   int = 2,
    seed:          int = 42,
) -> RobustnessSession:
    """
    Run a full robustness test session.

    Args:
        clean_image:   BGR clean reference document image.
        ground_truth:  {field: value} — expected extraction values.
        transforms:    Subset of transform families (None = all 14).
        max_variants:  Maximum number of degraded variants to test.
        max_workers:   ThreadPool parallelism (keep low to avoid OCR mutex).
        seed:          Reproducibility seed.

    Returns:
        RobustnessSession with all per-variant results.
    """
    session_id = str(uuid.uuid4())[:8]
    t0         = time.time()

    logger.info(
        "[robustness_runner] ══ Starting session=%s variants=%d workers=%d ══",
        session_id, max_variants, max_workers,
    )

    variants = generate_sweep(clean_image, transforms=transforms,
                              max_variants=max_variants, seed=seed)
    logger.info("[robustness_runner] Generated %d variants", len(variants))

    session = RobustnessSession(
        session_id=session_id,
        ground_truth=ground_truth,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_pipeline_on_variant, v, ground_truth, session_id): v
            for v in variants
        }
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                vr = fut.result()
                session.results.append(vr)
                logger.info(
                    "[robustness_runner] [%d/%d] %-35s acc=%.0f%% retries=%d elapsed=%.0fms",
                    done, len(variants), vr.variant_name,
                    vr.accuracy * 100, vr.total_retries, vr.elapsed_ms,
                )
            except Exception as exc:
                logger.error("[robustness_runner] Future error: %s", exc)

    session.elapsed_s = time.time() - t0
    smry = session.summary()
    logger.info(
        "[robustness_runner] ══ Done in %.1fs — success=%.0f%% field_acc=%s ══",
        session.elapsed_s,
        smry["success_rate"] * 100,
        smry["per_field_accuracy"],
    )
    return session
