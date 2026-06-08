"""
app/api/robustness_routes.py
=============================
Robustness Testing API Endpoints.

POST /api/v2/academic/robustness/run
  Upload a clean reference image + optional ground-truth fields.
  Runs the full adversarial benchmark and returns the DashboardReport.

GET  /api/v2/academic/robustness/report/{report_id}
  Retrieve a cached DashboardReport by ID.

GET  /api/v2/academic/robustness/transforms
  List available degradation transform names.

ISOLATION: Zero imports from Aadhaar / PAN / KYC modules.
"""

from __future__ import annotations

import json
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from app.core.logger import logger

router = APIRouter(prefix="/v2/academic/robustness", tags=["Robustness Testing"])

# In-memory report cache
_report_cache: dict = {}


def _decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image — ensure JPG/PNG format")
    return img


# ── List transforms ───────────────────────────────────────────────────────────

@router.get("/transforms", summary="List available degradation transforms")
def list_transforms():
    from app.academic_engine.testing.adversarial_generator import list_transforms
    return {"transforms": list_transforms()}


# ── Run benchmark ─────────────────────────────────────────────────────────────

@router.post("/run", summary="Run adversarial robustness benchmark")
async def run_robustness(
    file:          UploadFile = File(..., description="Clean reference document (JPG/PNG)"),
    ground_truth:  Optional[str] = Form(None,
        description='JSON string: {"percentage":"75.17","candidate_name":"Rahul Sharma",...}'),
    transforms:    Optional[str] = Form(None,
        description='JSON array of transform names, e.g. ["gaussian_blur","rotation"]'),
    max_variants:  int = Form(40, description="Max degraded variants to generate (10–100)"),
    max_workers:   int = Form(2,  description="Thread pool size (1–4)"),
    seed:          int = Form(42, description="Reproducibility seed"),
):
    """
    Run a full adversarial robustness benchmark on a clean reference document.

    Upload a clean scan + ground-truth field values.
    Returns a comprehensive DashboardReport with:
      - Overall robustness score (0-100)
      - Per-field accuracy
      - Per-transform accuracy
      - Failure clusters
      - Auto-tuning recommendations
    """
    if not file or not file.filename:
        raise HTTPException(400, "No file provided")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"}:
        raise HTTPException(400, f"Unsupported image format: .{ext}")

    max_variants = max(10, min(100, max_variants))
    max_workers  = max(1,  min(4,   max_workers))

    # Parse ground truth
    truth: dict = {}
    if ground_truth:
        try:
            truth = json.loads(ground_truth)
        except json.JSONDecodeError:
            raise HTTPException(400, "ground_truth must be valid JSON")

    # Parse transforms filter
    transform_filter = None
    if transforms:
        try:
            transform_filter = json.loads(transforms)
            if not isinstance(transform_filter, list):
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, "transforms must be a JSON array of strings")

    # Decode image
    raw = await file.read()
    try:
        image = _decode_image(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    logger.info(
        "[robustness_routes] Starting benchmark: file=%s size=%dx%d variants=%d gt_fields=%s",
        file.filename, image.shape[1], image.shape[0], max_variants, list(truth.keys()),
    )

    try:
        from app.academic_engine.testing.metrics_dashboard import run_full_benchmark
        report = run_full_benchmark(
            clean_image=image,
            ground_truth=truth,
            transforms=transform_filter,
            max_variants=max_variants,
            max_workers=max_workers,
            seed=seed,
        )
    except Exception as exc:
        logger.error("[robustness_routes] Benchmark failed: %s", exc)
        raise HTTPException(500, f"Benchmark error: {exc}")

    result = report.to_dict()
    _report_cache[report.report_id] = report

    logger.info("[robustness_routes] Benchmark complete: score=%d report=%s",
                report.score.overall, report.report_id)
    return result


# ── Get cached report ─────────────────────────────────────────────────────────

@router.get("/report/{report_id}", summary="Get a cached benchmark report")
def get_report(report_id: str):
    report = _report_cache.get(report_id)
    if not report:
        raise HTTPException(404, f"Report '{report_id}' not found. Run a benchmark first.")
    return report.to_dict()


# ── Markdown export ───────────────────────────────────────────────────────────

@router.get("/report/{report_id}/markdown", summary="Export report as Markdown")
def get_report_markdown(report_id: str):
    report = _report_cache.get(report_id)
    if not report:
        raise HTTPException(404, f"Report '{report_id}' not found.")
    return PlainTextResponse(report.to_markdown(), media_type="text/markdown")
