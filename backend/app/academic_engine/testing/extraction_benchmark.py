"""
academic_engine/testing/extraction_benchmark.py
=================================================
Field Accuracy Metrics + Robustness Score Engine.

Takes a RobustnessSession and computes:

  1. Per-field accuracy (percentage, name, CGPA, result, classification)
  2. Per-transform-family accuracy + degradation curves
  3. Severity-accuracy correlation
  4. Overall robustness score (0–100)
  5. Percentile ranking (excellent/good/fair/poor)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.academic_engine.testing.robustness_runner import RobustnessSession, VariantResult


@dataclass
class FieldBenchmark:
    field:         str
    accuracy:      float           # 0.0 – 1.0
    total:         int
    correct:       int
    per_transform: Dict[str, float]
    per_severity:  List[Tuple[float, bool]]   # [(severity, correct), ...]
    worst_transforms: List[str]               # bottom 3 families by accuracy

    def to_dict(self) -> Dict:
        return {
            "field":           self.field,
            "accuracy":        round(self.accuracy, 3),
            "accuracy_pct":    round(self.accuracy * 100, 1),
            "total":           self.total,
            "correct":         self.correct,
            "per_transform":   {k: round(v, 3) for k, v in self.per_transform.items()},
            "worst_transforms": self.worst_transforms,
        }


@dataclass
class RobustnessScore:
    overall:                int     # 0–100
    grade:                  str     # excellent/good/fair/poor
    field_scores:           Dict[str, int]          # per-field 0–100
    transform_scores:       Dict[str, int]          # per-transform 0–100
    recovery_rate:          float
    avg_retries:            float
    success_rate:           float
    total_variants:         int
    field_benchmarks:       List[FieldBenchmark]
    severity_curve:         List[Tuple[float, float]]   # [(severity, accuracy)]
    weakness_summary:       str

    def to_dict(self) -> Dict:
        return {
            "overall":            self.overall,
            "grade":              self.grade,
            "field_scores":       self.field_scores,
            "transform_scores":   self.transform_scores,
            "recovery_rate":      round(self.recovery_rate, 3),
            "avg_retries":        round(self.avg_retries, 2),
            "success_rate":       round(self.success_rate, 3),
            "total_variants":     self.total_variants,
            "severity_curve":     [(round(s, 2), round(a, 3)) for s, a in self.severity_curve],
            "weakness_summary":   self.weakness_summary,
            "field_benchmarks":   [fb.to_dict() for fb in self.field_benchmarks],
        }


# ── Score computation ─────────────────────────────────────────────────────────

_FIELD_WEIGHTS = {
    "percentage":   0.30,
    "candidate_name": 0.25,
    "cgpa":         0.20,
    "result":       0.15,
    "grade_class":  0.10,
}

_GRADE_THRESHOLDS = [
    (90, "excellent"),
    (75, "good"),
    (55, "fair"),
    (0,  "poor"),
]


def _grade(score: int) -> str:
    for threshold, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "poor"


def compute_field_benchmark(
    field: str,
    results: List[VariantResult],
) -> FieldBenchmark:
    relevant = [r for r in results if field in r.field_correct]
    if not relevant:
        return FieldBenchmark(
            field=field, accuracy=0.0, total=0, correct=0,
            per_transform={}, per_severity=[], worst_transforms=[],
        )

    correct = sum(1 for r in relevant if r.field_correct[field])
    acc     = correct / len(relevant)

    # Per-transform accuracy
    by_family: Dict[str, List[bool]] = {}
    for r in relevant:
        by_family.setdefault(r.transform, []).append(r.field_correct[field])
    per_transform = {k: round(sum(v) / len(v), 3) for k, v in by_family.items()}

    # Severity pairs
    per_severity = [(r.severity, r.field_correct[field]) for r in relevant]

    # Worst transforms
    sorted_fam = sorted(per_transform.items(), key=lambda x: x[1])
    worst = [k for k, _ in sorted_fam[:3]]

    return FieldBenchmark(
        field=field,
        accuracy=acc,
        total=len(relevant),
        correct=correct,
        per_transform=per_transform,
        per_severity=per_severity,
        worst_transforms=worst,
    )


def compute_robustness_score(session: RobustnessSession) -> RobustnessScore:
    """
    Compute comprehensive robustness score from a test session.
    """
    results = session.results
    if not results:
        return RobustnessScore(
            overall=0, grade="poor",
            field_scores={}, transform_scores={},
            recovery_rate=0.0, avg_retries=0.0,
            success_rate=0.0, total_variants=0,
            field_benchmarks=[], severity_curve=[],
            weakness_summary="No results available.",
        )

    # ── Field benchmarks ──────────────────────────────────────────────────────
    all_fields   = list(_FIELD_WEIGHTS.keys())
    benchmarks   = [compute_field_benchmark(f, results) for f in all_fields]
    field_scores = {
        fb.field: int(round(fb.accuracy * 100))
        for fb in benchmarks
    }

    # ── Weighted overall score ────────────────────────────────────────────────
    weighted = sum(
        field_scores.get(f, 0) * w
        for f, w in _FIELD_WEIGHTS.items()
    )

    # Penalise high avg retry counts
    avg_retries = session.avg_retries()
    retry_penalty = min(max(0.0, (avg_retries - 2) * 3), 10)

    # Bonus for high recovery rate
    recovery = session.recovery_rate()
    rec_bonus = recovery * 5

    overall = max(0, min(100, int(round(weighted - retry_penalty + rec_bonus))))

    # ── Per-transform scores ──────────────────────────────────────────────────
    by_family: Dict[str, List[float]] = {}
    for r in results:
        by_family.setdefault(r.transform, []).append(r.accuracy)
    transform_scores = {k: int(round(sum(v) / len(v) * 100))
                        for k, v in by_family.items()}

    # ── Severity curve ────────────────────────────────────────────────────────
    # Group results by severity bucket (0.1 buckets)
    buckets: Dict[float, List[float]] = {}
    for r in results:
        bucket = round(round(r.severity / 0.1) * 0.1, 1)
        buckets.setdefault(bucket, []).append(r.accuracy)
    severity_curve = sorted(
        [(s, sum(accs) / len(accs)) for s, accs in buckets.items()]
    )

    # ── Weakness summary ──────────────────────────────────────────────────────
    weak_fields  = [f for f, s in field_scores.items() if s < 70]
    weak_transforms = [t for t, s in transform_scores.items() if s < 60]
    parts = []
    if weak_fields:
        parts.append(f"Weak fields: {', '.join(weak_fields)}")
    if weak_transforms:
        parts.append(f"Weak transforms: {', '.join(weak_transforms[:3])}")
    if overall >= 90:
        parts = ["Engine is robust across all degradation types."]
    weakness_summary = " | ".join(parts) or "No significant weaknesses detected."

    # ── Success rate ──────────────────────────────────────────────────────────
    success_rate = session.success_count() / max(len(results), 1)

    return RobustnessScore(
        overall=overall,
        grade=_grade(overall),
        field_scores=field_scores,
        transform_scores=transform_scores,
        recovery_rate=recovery,
        avg_retries=avg_retries,
        success_rate=success_rate,
        total_variants=len(results),
        field_benchmarks=benchmarks,
        severity_curve=severity_curve,
        weakness_summary=weakness_summary,
    )
