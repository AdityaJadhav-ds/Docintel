"""
pdf_engine/multi_page_merger.py
================================
STEP 6 — Intelligent multi-page result merging.

Handles B.Tech/M.Tech transcripts where:
  - Page 1 : name, URN, branch, enrollment
  - Pages 2–N: semester tables (SPI, SGPA per semester)
  - Last page: aggregate CGPA, final percentage, result

Merge rules:
  - NEVER overwrite a high-confidence field with a lower-confidence one
  - Prefer REPEATED consistent values across pages
  - Candidate name: best confidence across all pages
  - Percentage/CGPA: prefer summary page (last page)
  - Result: prefer summary page
  - SPI values: merged into list from all semester pages

Returns a single unified result dict in the same shape as MasterPipeline output.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("docvalidator")


def _get_field_confidence(result: dict, field_path: str) -> float:
    """Extract confidence for a field from a pipeline result dict."""
    # Try valid_fields path (MasterPipeline output)
    vf = result.get("valid_fields", {})
    if field_path in vf:
        f = vf[field_path]
        if isinstance(f, dict):
            return float(f.get("confidence", 0.0))
    # Try extracted_data.fields path
    ef = result.get("extracted_data", {}).get("fields", {})
    if field_path in ef:
        f = ef[field_path]
        if isinstance(f, dict):
            return float(f.get("confidence", 0.0))
    return 0.0


def _get_field_value(result: dict, field_path: str) -> Optional[Any]:
    """Extract value for a field from a pipeline result dict."""
    vf = result.get("valid_fields", {})
    if field_path in vf:
        f = vf[field_path]
        if isinstance(f, dict):
            return f.get("value")
        return f
    ef = result.get("extracted_data", {}).get("fields", {})
    if field_path in ef:
        f = ef[field_path]
        if isinstance(f, dict):
            return f.get("value")
        return f
    return None


def _pick_best_field(
    page_results: List[dict],
    field_name: str,
    prefer_role: Optional[str] = None,
) -> Optional[Any]:
    """
    Pick the best value for a field across all pages.

    Strategy:
      1. If prefer_role is set, first check pages with that role
      2. Among candidates, pick highest confidence
      3. Consistency bonus: if same value appears on 2+ pages, prefer it

    Returns the winning value (or None).
    """
    candidates = []
    for pr in page_results:
        val  = _get_field_value(pr["result"], field_name)
        conf = _get_field_confidence(pr["result"], field_name)
        role = pr.get("role", "general")
        if val is not None:
            candidates.append({
                "value":      val,
                "confidence": conf,
                "role":       role,
            })

    if not candidates:
        return None

    # Consistency: group by value, count occurrences
    value_groups: Dict[str, dict] = {}
    for c in candidates:
        key = str(c["value"]).strip().upper()
        if key not in value_groups:
            value_groups[key] = {"value": c["value"], "conf": c["confidence"], "count": 0}
        value_groups[key]["count"] += 1
        if c["confidence"] > value_groups[key]["conf"]:
            value_groups[key]["conf"] = c["confidence"]

    # Score: confidence + consistency bonus (0.1 per extra occurrence)
    def _score(g):
        role_bonus = 0.15 if prefer_role and any(
            c["role"] == prefer_role for c in candidates
            if str(c["value"]).strip().upper() == str(g["value"]).strip().upper()
        ) else 0.0
        return g["conf"] + (g["count"] - 1) * 0.10 + role_bonus

    best = max(value_groups.values(), key=_score)
    return best["value"]


def _merge_spi_list(page_results: List[dict]) -> List[str]:
    """
    Collect SPI/SGPA values from all semester pages.
    Returns ordered list (semester 1 first).
    """
    spi_values = []
    for pr in sorted(page_results, key=lambda r: r.get("page_number", 0)):
        result = pr["result"]
        # Look for SPI in multiple possible field names
        for field in ("spi", "sgpa", "semester_gpa"):
            val = _get_field_value(result, field)
            if val is not None:
                spi_values.append(str(val))
                break
    return spi_values


def merge_page_results(
    page_results: List[dict],
    upload_id: str = "merged",
) -> dict:
    """
    STEP 6 — Merge results from all PDF pages into one unified output.

    Args:
        page_results: List of {page_number, role, result (MasterPipeline output)}
        upload_id:    For debug labelling

    Returns:
        Single result dict (same shape as MasterPipeline.process_document())
    """
    if not page_results:
        return {
            "status": "error",
            "upload_id": upload_id,
            "message": "No pages to merge",
            "valid_fields": {},
            "rejected_fields": {},
            "warnings": ["PDF produced no processable pages"],
            "extracted_data": {"fields": {}, "table_data": {}},
            "telemetry": {"total_time_seconds": 0, "stage_trace": {}},
        }

    if len(page_results) == 1:
        # Single page — return directly, no merge needed
        r = page_results[0]["result"]
        logger.info("[merger] Single page PDF — returning page 1 result directly")
        return r

    logger.info("[merger] Merging %d page results (upload_id=%s)", len(page_results), upload_id)

    # ── Pick best value for each standard field ──────────────────────────────
    # Identity fields: prefer header page (page 1)
    name       = _pick_best_field(page_results, "name",        prefer_role="header")
    urn        = _pick_best_field(page_results, "urn",         prefer_role="header")
    prn        = _pick_best_field(page_results, "prn",         prefer_role="header")
    branch     = _pick_best_field(page_results, "branch",      prefer_role="header")
    enrollment = _pick_best_field(page_results, "enrollment",  prefer_role="header")
    board      = _pick_best_field(page_results, "board_university", prefer_role="header")
    year       = _pick_best_field(page_results, "passing_year",    prefer_role="summary")

    # Academic fields: prefer summary page (last page)
    cgpa       = _pick_best_field(page_results, "cgpa",        prefer_role="summary")
    percentage = _pick_best_field(page_results, "percentage",  prefer_role="summary")
    result_val = _pick_best_field(page_results, "result",      prefer_role="summary")
    grade      = _pick_best_field(page_results, "grade_class", prefer_role="summary")

    # SPI: collect from all semester pages
    spi_list = _merge_spi_list(page_results)

    # ── Build merged valid_fields ────────────────────────────────────────────
    merged_valid_fields: Dict[str, Any] = {}

    def _add(field_name: str, value: Any, conf: float = 0.7):
        if value is not None:
            merged_valid_fields[field_name] = {
                "value":                value,
                "confidence":           conf,
                "validated":            True,
                "extraction_strategy":  "multi_page_merger",
                "source_label":         "merged_pages",
                "source_region":        (0, 0, 0, 0),
            }

    _add("name",            name,       0.85)
    _add("urn",             urn,        0.85)
    _add("prn",             prn,        0.85)
    _add("branch",          branch,     0.80)
    _add("enrollment",      enrollment, 0.80)
    _add("board_university", board,     0.80)
    _add("passing_year",    year,       0.80)
    _add("cgpa",            cgpa,       0.85)
    _add("percentage",      percentage, 0.85)
    _add("result",          result_val, 0.90)
    _add("grade_class",     grade,      0.80)

    if spi_list:
        _add("spi_list", spi_list, 0.75)

    # ── Gather table data from all pages ────────────────────────────────────
    merged_table: Dict[str, Any] = {}
    all_warnings: List[str] = []
    total_time = 0.0

    for pr in page_results:
        r = pr["result"]
        td = r.get("extracted_data", {}).get("table_data", {})
        if td:
            merged_table.update(td)
        all_warnings.extend(r.get("warnings", []))
        total_time += r.get("telemetry", {}).get("total_time_seconds", 0.0)

    # ── Collect rejected_fields from any page ────────────────────────────────
    merged_rejected: Dict[str, Any] = {}
    for pr in page_results:
        merged_rejected.update(pr["result"].get("rejected_fields", {}))

    # ── Compute merged status ────────────────────────────────────────────────
    has_name    = "name" in merged_valid_fields
    has_grade   = any(k in merged_valid_fields for k in ("cgpa", "percentage", "result"))
    merged_status = "success" if (has_name and has_grade) else "partial"

    merged = {
        "status":           merged_status,
        "upload_id":        upload_id,
        "valid_fields":     merged_valid_fields,
        "rejected_fields":  merged_rejected,
        "warnings":         list(set(all_warnings)),
        "extracted_data": {
            "fields":      merged_valid_fields,
            "table_data":  merged_table,
        },
        "telemetry": {
            "total_time_seconds": round(total_time, 2),
            "stage_trace":        {"merger": {"pages": len(page_results)}},
            "warnings":           list(set(all_warnings)),
            "ocr_confidence":     max(
                (pr["result"].get("telemetry", {}).get("ocr_confidence", 0.0)
                 for pr in page_results),
                default=0.0,
            ),
        },
        "debug_lab": {
            "merger": {
                "pages_processed": len(page_results),
                "page_roles":      [pr.get("role") for pr in page_results],
                "spi_collected":   spi_list,
            }
        },
    }

    logger.info(
        "[merger] Merge complete: status=%s fields=%d name=%r cgpa=%r pct=%r",
        merged_status, len(merged_valid_fields), name, cgpa, percentage,
    )

    return merged
