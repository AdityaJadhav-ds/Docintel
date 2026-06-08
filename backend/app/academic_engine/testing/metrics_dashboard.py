"""
academic_engine/testing/metrics_dashboard.py
=============================================
Full Metrics Dashboard + Report Generator.

Orchestrates the full testing cycle and produces a structured report:
  - Robustness score + grade
  - Field accuracy breakdown
  - Failure cluster analysis
  - Region heatmap
  - Auto-tuning recommendations
  - Variant-level detail table

Public API:
  run_full_benchmark(image, ground_truth, **kwargs) -> DashboardReport
  DashboardReport.to_dict()           -> JSON-serialisable dict
  DashboardReport.to_markdown()       -> Markdown text report
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logger import logger
from app.academic_engine.testing.robustness_runner import (
    RobustnessSession, run_robustness_test,
)
from app.academic_engine.testing.extraction_benchmark import (
    RobustnessScore, compute_robustness_score,
)
from app.academic_engine.testing.failure_clustering import (
    FailureCluster, cluster_failures, build_region_heatmap, generate_recommendations,
)


# ── Dashboard report ──────────────────────────────────────────────────────────

@dataclass
class DashboardReport:
    report_id:        str
    session:          RobustnessSession
    score:            RobustnessScore
    clusters:         List[FailureCluster]
    region_heatmap:   Dict[str, int]
    recommendations:  List[str]
    generated_at:     float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        smry = self.session.summary()
        return {
            "report_id":       self.report_id,
            "generated_at":    self.generated_at,
            "robustness_score": self.score.to_dict(),
            "session_summary": smry,
            "variant_results": [r.to_dict() for r in self.session.results],
            "failure_clusters": [c.to_dict() for c in self.clusters],
            "region_heatmap":  self.region_heatmap,
            "recommendations": self.recommendations,
        }

    def to_markdown(self) -> str:
        s = self.score
        lines = [
            "# Academic Engine Robustness Report",
            "",
            f"**Report ID:** {self.report_id}  ",
            f"**Total Variants Tested:** {s.total_variants}  ",
            f"**Engine Overall Score:** {s.overall}/100 ({s.grade.upper()})  ",
            f"**Success Rate:** {s.success_rate:.1%}  ",
            f"**Recovery Rate:** {s.recovery_rate:.1%}  ",
            f"**Avg Retries per Field:** {s.avg_retries:.1f}  ",
            "",
            "## Field Accuracy",
            "",
            "| Field | Score | Accuracy |",
            "|-------|-------|----------|",
        ]
        for f, score in s.field_scores.items():
            lines.append(f"| {f} | {score}/100 | {score:.0f}% |")

        lines += [
            "",
            "## Accuracy by Degradation Type",
            "",
            "| Transform | Score |",
            "|-----------|-------|",
        ]
        for t, score in sorted(s.transform_scores.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {t.replace('_',' ')} | {score}/100 |")

        if self.clusters:
            lines += ["", "## Top Failure Clusters", ""]
            for c in self.clusters[:8]:
                lines.append(f"- **[{c.cluster_id}]** {c.description} ({c.count} cases)")

        if self.region_heatmap:
            lines += ["", "## Region Failure Heatmap", "", "| Region | Failures |", "|--------|---------|"]
            for region, cnt in sorted(self.region_heatmap.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| {region.replace('_',' ')} | {cnt} |")

        lines += ["", "## Recommendations", ""]
        for rec in self.recommendations:
            lines.append(f"{rec}  ")

        return "\n".join(lines)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_full_benchmark(
    clean_image:    np.ndarray,
    ground_truth:   Dict[str, Optional[str]],
    transforms:     Optional[List[str]] = None,
    max_variants:   int = 60,
    max_workers:    int = 2,
    seed:           int = 42,
) -> DashboardReport:
    """
    Run the complete adversarial benchmark pipeline.

    Args:
        clean_image:    BGR clean reference image.
        ground_truth:   Expected extraction values (field → value).
        transforms:     Subset of transform names (None = all 14).
        max_variants:   Maximum degraded variants to generate.
        max_workers:    ThreadPool parallelism for pipeline calls.
        seed:           Reproducibility seed.

    Returns:
        DashboardReport with full analysis.
    """
    report_id = str(uuid.uuid4())[:12]
    logger.info("[metrics_dashboard] ══ Benchmark %s starting ══", report_id)

    # 1. Run robustness tests
    session = run_robustness_test(
        clean_image=clean_image,
        ground_truth=ground_truth,
        transforms=transforms,
        max_variants=max_variants,
        max_workers=max_workers,
        seed=seed,
    )

    # 2. Compute score
    score = compute_robustness_score(session)
    logger.info("[metrics_dashboard] Score: %d (%s)", score.overall, score.grade)

    # 3. Cluster failures
    clusters = cluster_failures(session, min_cluster_size=2)
    logger.info("[metrics_dashboard] Clusters: %d", len(clusters))

    # 4. Region heatmap
    heatmap = build_region_heatmap(session)

    # 5. Recommendations
    recommendations = generate_recommendations(clusters, heatmap, score.to_dict())
    logger.info("[metrics_dashboard] Recommendations: %d", len(recommendations))

    report = DashboardReport(
        report_id=report_id,
        session=session,
        score=score,
        clusters=clusters,
        region_heatmap=heatmap,
        recommendations=recommendations,
    )

    logger.info(
        "[metrics_dashboard] ══ Benchmark complete: score=%d variants=%d clusters=%d ══",
        score.overall, session.total_variants(), len(clusters),
    )
    return report
