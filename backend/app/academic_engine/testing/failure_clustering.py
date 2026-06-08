"""
academic_engine/testing/failure_clustering.py
===============================================
Automatic Failure Clustering Engine.

Groups extraction failures by:
  1. Degradation family (blur / noise / compression / etc.)
  2. Field type (percentage / name / result)
  3. Severity range (mild / moderate / severe)
  4. OCR failure mode (empty / invalid-format / near-miss / hallucinated)

Produces:
  - Cluster objects with representative examples and counts
  - Ranked list of most common failure patterns
  - Region heatmap grid (which document region failed most)
  - Auto-tuning insight recommendations
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.academic_engine.testing.robustness_runner import RobustnessSession, VariantResult


# ── Failure record ────────────────────────────────────────────────────────────

@dataclass
class FailureRecord:
    variant:   str
    transform: str
    severity:  float
    field:     str
    extracted: Optional[str]
    expected:  Optional[str]
    reason:    Optional[str]    # from adaptive failure_reasons
    mode:      str              # "empty" | "invalid" | "near_miss" | "wrong"


# ── Cluster ───────────────────────────────────────────────────────────────────

@dataclass
class FailureCluster:
    cluster_id:   str
    label:        str
    transform:    str
    field:        str
    mode:         str
    severity_range: Tuple[float, float]    # (min, max)
    count:        int
    examples:     List[FailureRecord]      # up to 3

    @property
    def description(self) -> str:
        sev = (self.severity_range[0] + self.severity_range[1]) / 2
        sev_label = "mild" if sev < 0.33 else "moderate" if sev < 0.67 else "severe"
        return (
            f"{self.field.upper()} extraction fails under {sev_label} "
            f"{self.transform.replace('_', ' ')} (mode: {self.mode})"
        )

    def to_dict(self) -> Dict:
        return {
            "cluster_id":     self.cluster_id,
            "label":          self.label,
            "transform":      self.transform,
            "field":          self.field,
            "mode":           self.mode,
            "severity_range": [round(self.severity_range[0], 2),
                                round(self.severity_range[1], 2)],
            "count":          self.count,
            "description":    self.description,
        }


# ── Failure mode classifier ───────────────────────────────────────────────────

_NEAR_MISS_NUMERIC_TOL = 3.0    # within 3 units of expected


def _classify_mode(
    extracted: Optional[str],
    expected:  Optional[str],
    field_name: str,
) -> str:
    if not extracted or not extracted.strip():
        return "empty"

    if expected is None:
        return "unknown"

    # Numeric near-miss
    if field_name in ("percentage", "cgpa"):
        try:
            ev = float(extracted)
            gt = float(expected)
            if abs(ev - gt) <= _NEAR_MISS_NUMERIC_TOL:
                return "near_miss"
        except (ValueError, TypeError):
            pass
        # Is it a valid-looking number but wrong value?
        if re.search(r'\d{1,3}(?:\.\d{1,2})?', extracted):
            return "invalid"
        return "wrong"

    # Text fields
    if extracted.strip().upper() == expected.strip().upper():
        return "correct"    # shouldn't reach here (already filtered)

    # Partial match
    if expected and extracted:
        exp_words = set(expected.upper().split())
        ext_words = set(extracted.upper().split())
        if exp_words & ext_words:
            return "near_miss"

    return "wrong"


# ── Main clustering ───────────────────────────────────────────────────────────

def cluster_failures(
    session:     RobustnessSession,
    min_cluster_size: int = 2,
) -> List[FailureCluster]:
    """
    Cluster all failures in a RobustnessSession.

    Returns:
        List of FailureCluster sorted by count (descending).
    """
    # Collect raw failure records
    failures: List[FailureRecord] = []
    truth = session.ground_truth

    for r in session.results:
        for f, correct in r.field_correct.items():
            if not correct:
                extracted = r.extracted.get(f)
                expected  = truth.get(f)
                mode      = _classify_mode(extracted, expected, f)
                reason    = r.failure_reasons.get(f)
                failures.append(FailureRecord(
                    variant=r.variant_name, transform=r.transform,
                    severity=r.severity, field=f,
                    extracted=extracted, expected=expected,
                    reason=reason, mode=mode,
                ))

    # Group by (transform_family, field, mode)
    groups: Dict[Tuple, List[FailureRecord]] = defaultdict(list)
    for fr in failures:
        key = (fr.transform, fr.field, fr.mode)
        groups[key].append(fr)

    clusters: List[FailureCluster] = []
    cid = 0
    for (transform, field_name, mode), records in groups.items():
        if len(records) < min_cluster_size:
            continue
        severities = [r.severity for r in records]
        cid += 1
        clusters.append(FailureCluster(
            cluster_id    = f"C{cid:03d}",
            label         = f"{field_name}:{transform}:{mode}",
            transform     = transform,
            field         = field_name,
            mode          = mode,
            severity_range= (min(severities), max(severities)),
            count         = len(records),
            examples      = records[:3],
        ))

    return sorted(clusters, key=lambda c: c.count, reverse=True)


# ── OCR Region Heatmap ────────────────────────────────────────────────────────

# Map fields to rough document region labels
_FIELD_REGION = {
    "candidate_name": "candidate_zone",
    "percentage":     "summary_zone",
    "cgpa":           "summary_zone",
    "result":         "summary_zone",
    "grade_class":    "summary_zone",
    "board_university": "header_zone",
    "passing_year":   "header_zone",
}


def build_region_heatmap(session: RobustnessSession) -> Dict[str, int]:
    """
    Count failures per document region for a heatmap visualization.

    Returns:
        Dict of region → failure_count
    """
    heatmap: Dict[str, int] = defaultdict(int)
    for r in session.results:
        for f, correct in r.field_correct.items():
            if not correct:
                region = _FIELD_REGION.get(f, "unknown_zone")
                heatmap[region] += 1
    return dict(heatmap)


# ── Recommendations ───────────────────────────────────────────────────────────

def generate_recommendations(
    clusters:  List[FailureCluster],
    heatmap:   Dict[str, int],
    score_dict: Dict,
) -> List[str]:
    """
    Generate human-readable auto-tuning recommendations.
    """
    recs: List[str] = []

    # Top failure clusters
    for c in clusters[:5]:
        sev_mid = (c.severity_range[0] + c.severity_range[1]) / 2
        if c.mode == "empty":
            recs.append(
                f"❌ {c.field.upper()} ROI returns empty under {c.transform.replace('_',' ')} "
                f"(severity {sev_mid:.2f}) — consider wider fallback crop strategy."
            )
        elif c.mode == "near_miss":
            recs.append(
                f"⚠ {c.field.upper()} near-miss under {c.transform.replace('_',' ')} "
                f"— confidence_recovery module may need expanded char substitution table."
            )
        elif c.mode == "invalid":
            recs.append(
                f"⚠ {c.field.upper()} invalid OCR text under {c.transform.replace('_',' ')} "
                f"— adaptive threshold preprocessing variant should be prioritised."
            )
        else:
            recs.append(
                f"⚠ {c.field.upper()} wrong extraction under {c.transform.replace('_',' ')} "
                f"— review spatial anchor mapping for this transform family."
            )

    # Region heatmap insights
    sorted_regions = sorted(heatmap.items(), key=lambda x: x[1], reverse=True)
    for region, count in sorted_regions[:2]:
        if count > 5:
            recs.append(
                f"📍 {region.replace('_', ' ').title()} has {count} failures "
                f"— consider additional preprocessing for this zone."
            )

    # Transform-level insights from benchmark
    ts = score_dict.get("transform_scores", {})
    worst_transforms = sorted(ts.items(), key=lambda x: x[1])[:3]
    for t, score in worst_transforms:
        if score < 60:
            recs.append(
                f"⚡ '{t.replace('_',' ')}' transform has only {score}% accuracy "
                f"— scanner engine restoration pipeline should tackle this case."
            )

    if not recs:
        recs.append("✅ Engine is performing well. No critical recommendations.")

    return recs
