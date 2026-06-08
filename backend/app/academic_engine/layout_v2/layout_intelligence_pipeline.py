"""
academic_engine/layout_v2/layout_intelligence_pipeline.py
==========================================================
Layout Intelligence Pipeline v2 — master orchestrator.

Full flow:
  RESTORED_SCAN
    ↓  layout_classifier   → Detect SSC/HSC/Degree/Certificate/Diploma variant
    ↓  zone_segmenter      → 5 adaptive zones (Header/Candidate/Subjects/Summary/Noise)
    ↓  table_detector      → Mask/exclude subject table from extraction
    ↓  summary_locator     → Pinpoint %/CGPA/Result sub-ROIs within Summary zone
    ↓  roi_detector        → Build field-specific preprocessed crops
    ↓  adaptive extraction → 4-tier self-healing OCR (retry+fallback+recovery)
    ↓  anchor_mapper       → Spatial label→value extraction
    ↓  field_validation    → Range checks + format validation
    ↓  priority_selector   → Return highest-value metric (CGPA>%>grade>result)
    ↓  FINAL RESULT DICT

ISOLATION: Zero imports from Aadhaar / PAN / KYC modules.
"""

from __future__ import annotations

import re
import time
import base64
import cv2
import numpy as np
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.logger import logger

# ── layout_v2 imports ─────────────────────────────────────────────────────────
from app.academic_engine.layout_v2.zone_segmenter    import segment_document, SegmentationResult
from app.academic_engine.layout_v2.table_detector    import detect_table
from app.academic_engine.layout_v2.summary_locator   import locate_summary, SummaryLocatorResult
from app.academic_engine.layout_v2.roi_detector      import extract_rois, ROISpec
from app.academic_engine.layout_v2.anchor_mapper     import map_anchor_fields
from app.academic_engine.layout_v2.layout_classifier import classify_layout

# ── Adaptive ROI Engine ───────────────────────────────────────────────────────
try:
    from app.academic_engine.adaptive.roi_retry_engine import (
        run_adaptive_extraction, get_adaptive_metrics,
    )
    from app.academic_engine.adaptive.candidate_name_ranker import extract_best_name
    _ADAPTIVE_AVAILABLE = True
except ImportError as _adp_err:
    logger.warning("[layout_v2_pipeline] adaptive engine not available: %s", _adp_err)
    _ADAPTIVE_AVAILABLE = False


# ── Debug helpers ─────────────────────────────────────────────────────────────

_DEBUG_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "academic_debug"


def _save_debug_img(bgr: np.ndarray, session: str, name: str) -> Optional[str]:
    try:
        out_dir = _DEBUG_ROOT / session
        out_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_dir / f"{name}.jpg"), bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    except Exception as exc:
        logger.warning("[layout_v2_pipeline] Debug save failed: %s", exc)
    try:
        _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buf.tobytes()).decode("utf-8")
    except Exception:
        return None


def _annotate_zones(image: np.ndarray, zones: SegmentationResult) -> np.ndarray:
    COLORS = {
        "header":    (255, 200, 0),
        "candidate": (0, 220, 50),
        "subjects":  (50, 50, 200),
        "summary":   (0, 128, 255),
        "noise":     (150, 0, 200),
    }
    vis = image.copy()
    for name, zone in zones.items():
        if zone.crop is None:
            continue
        x1, y1, x2, y2 = zone.rect
        color = COLORS.get(name, (200, 200, 200))
        cv2.rectangle(vis, (x1, y1), (x2, y2), color, 3)
        label = zone.label.split("—")[1].strip() if "—" in zone.label else name
        cv2.putText(vis, label, (x1 + 5, y1 + 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return vis


# ── Single-pass OCR (fallback when adaptive unavailable) ─────────────────────

def _ocr_with_config(preprocessed: np.ndarray, config: str) -> Tuple[str, float]:
    try:
        # import pytesseract
        text = pytesseract.image_to_string(preprocessed, config=config, lang="eng")
        data = pytesseract.image_to_data(
            preprocessed, config=config, lang="eng",
            output_type=pytesseract.Output.DICT,
        )
        confs = [c for c in data["conf"] if isinstance(c, (int, float)) and c > 0]
        conf  = (sum(confs) / len(confs) / 100.0) if confs else 0.3
        return text.strip(), round(conf, 3)
    except Exception as exc:
        logger.warning("[layout_v2_pipeline] Tesseract failed: %s", exc)
        return "", 0.0


def _ocr_easyocr(bgr: np.ndarray) -> Tuple[str, float]:
    try:
        from app.academic_engine.ocr.hybrid_ocr import _run_easyocr
        r = _run_easyocr(bgr)
        return r.get("text", ""), r.get("confidence", 0.0)
    except Exception as exc:
        logger.warning("[layout_v2_pipeline] EasyOCR failed: %s", exc)
        return "", 0.0


def _ocr_roi(roi_spec: ROISpec, use_easyocr: bool = False) -> Tuple[str, float, str]:
    pre = roi_spec.preprocessed
    raw = roi_spec.raw_crop
    if pre is None:
        return "", 0.0, "none"
    tess_text, tess_conf = _ocr_with_config(pre, roi_spec.ocr_config)
    if not use_easyocr or raw is None:
        return tess_text, tess_conf, "tesseract"
    easy_text, easy_conf = _ocr_easyocr(raw)
    if easy_conf > tess_conf and easy_text.strip():
        return easy_text, easy_conf, "easyocr"
    return tess_text, tess_conf, "tesseract"


# ── Field validators ──────────────────────────────────────────────────────────

RESULT_VALUES = {
    "PASS", "PASSED", "FAIL", "FAILED",
    "DISTINCTION", "FIRST CLASS WITH DISTINCTION",
    "FIRST CLASS", "SECOND CLASS", "THIRD CLASS",
    "COMPARTMENT", "ABSENT", "WITHHELD",
}


def _validate_percentage(raw: str) -> Optional[str]:
    nums = re.findall(r"\d{1,3}(?:\.\d{1,2})?", raw.replace(",", "."))
    for n in nums:
        try:
            v = float(n)
            if 0.0 < v <= 100.0:
                return str(round(v, 2))
        except ValueError:
            pass
    return None


def _validate_cgpa(raw: str) -> Optional[str]:
    nums = re.findall(r"\d{1,2}(?:\.\d{1,2})?", raw.replace(",", "."))
    for n in nums:
        try:
            v = float(n)
            if 0.0 < v <= 10.0:
                return str(round(v, 2))
        except ValueError:
            pass
    return None


def _validate_result(raw: str) -> Optional[str]:
    clean = re.sub(r"[^A-Za-z\s]", "", raw).upper().strip()
    if clean in RESULT_VALUES:
        return clean
    for kw in ["DISTINCTION", "FIRST CLASS", "SECOND CLASS", "THIRD CLASS",
               "PASS", "FAIL", "COMPARTMENT", "ABSENT"]:
        if kw in clean:
            return kw
    return None


def _validate_name(raw: str) -> Optional[str]:
    clean = re.sub(r"[^A-Za-z\s\.]", "", raw).strip()
    words = clean.split()
    if 2 <= len(words) <= 6 and all(len(w) >= 2 for w in words):
        return " ".join(w.capitalize() for w in words)
    return None


def _validate_year(raw: str) -> Optional[str]:
    m = re.search(r"20\d{2}", raw)
    return m.group(0) if m else None


# ── Priority selector ─────────────────────────────────────────────────────────

def _select_primary_metric(
    percentage: Optional[str],
    cgpa: Optional[str],
    result: Optional[str],
    grade_class: Optional[str],
) -> Dict[str, Optional[str]]:
    """Priority: CGPA > Percentage > Grade/Result"""
    if cgpa:
        return {"percentage": None,       "cgpa": cgpa, "grade_class": grade_class, "result": result}
    if percentage:
        return {"percentage": percentage, "cgpa": None, "grade_class": grade_class, "result": result}
    return {"percentage": None,           "cgpa": None, "grade_class": grade_class, "result": result}


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_layout_intelligence(
    image:        np.ndarray,
    session_id:   str,
    quick_text:   str = "",
    debug:        bool = True,
    original_img: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Execute the full Layout Intelligence v2 pipeline on a restored document image.
    original_img: the pre-restoration image, used for color-channel percentage OCR.
    """
    t0      = time.time()
    engines: List[str] = []
    debug_images: Dict[str, Optional[str]] = {}

    logger.info("[layout_v2_pipeline] ══ Starting v2 session=%s ══", session_id)

    # ── Stage 1: Layout classification ───────────────────────────────────────
    variant = classify_layout(quick_text, img=image)
    logger.info("[layout_v2_pipeline] Layout class: %s", variant.layout_class)

    # ── Stage 2: Zone segmentation ────────────────────────────────────────────
    zones: SegmentationResult = segment_document(image, ocr_text=quick_text)

    if debug:
        vis = _annotate_zones(image, zones)
        debug_images["zones_annotated"] = _save_debug_img(vis, session_id, "layout_zones")
        for zname, zone in zones.items():
            if zone.crop is not None:
                debug_images[f"zone_{zname}"] = _save_debug_img(
                    zone.crop, session_id, f"zone_{zname}"
                )

    # ── Stage 3: Table detection metadata ────────────────────────────────────
    table_meta     = zones.get("subjects")
    table_detected = bool(table_meta and table_meta.metadata.get("table_detected"))

    # ── Stage 4: Summary locator (word-level anchor detection) ────────────────
    summary_zone = zones.get("summary")
    summary_text = ""
    summary_result: Optional[SummaryLocatorResult] = None

    if summary_zone and summary_zone.crop is not None:
        # For color-channel extraction, prefer original image if available
        # (restoration may bleach color channels, breaking cyan-cell OCR)
        if original_img is not None:
            orig_zones = segment_document(original_img, ocr_text=quick_text)
            orig_summary = orig_zones.get("summary")
            summary_for_color = orig_summary.crop if orig_summary and orig_summary.crop is not None else summary_zone.crop
        else:
            summary_for_color = summary_zone.crop

        summary_result = locate_summary(summary_zone.crop, color_crop=summary_for_color)
        summary_text   = summary_result.full_text if summary_result else ""
        if debug and summary_result:
            for rname, froi in summary_result.get_all_rois().items():
                if froi and froi.roi is not None:
                    debug_images[f"roi_{rname}"] = _save_debug_img(
                        froi.roi, session_id, f"roi_{rname}"
                    )

    # ── Stage 5: Build field-specific ROIs ────────────────────────────────────
    roi_specs = extract_rois(zones, summary_locator_result=summary_result)

    # ── Stage 6: Adaptive ROI Extraction (4-tier retry system) ───────────────
    summary_zone_image = summary_zone.crop if summary_zone else None
    summary_words      = summary_result.debug_words if summary_result else []

    zone_texts:       Dict[str, str]   = {}
    zone_confs:       Dict[str, float] = {}
    adaptive_results: Dict             = {}
    failure_reasons:  Dict             = {}

    if _ADAPTIVE_AVAILABLE and summary_zone_image is not None:
        pct_froi  = summary_result.percentage_roi if summary_result else None
        cgpa_froi = summary_result.cgpa_roi        if summary_result else None
        res_froi  = summary_result.result_roi      if summary_result else None
        cand_zone = zones.get("candidate")

        fields_config = {
            "percentage": {
                "primary_roi": pct_froi.roi        if pct_froi  else None,
                "zone_image":  summary_zone_image,
                "anchor_bbox": pct_froi.value_bbox  if pct_froi  else None,
                "zone_words":  summary_words,
            },
            "cgpa": {
                "primary_roi": cgpa_froi.roi        if cgpa_froi else None,
                "zone_image":  summary_zone_image,
                "anchor_bbox": cgpa_froi.value_bbox if cgpa_froi else None,
                "zone_words":  summary_words,
            },
            "result": {
                "primary_roi": res_froi.roi         if res_froi  else None,
                "zone_image":  summary_zone_image,
                "anchor_bbox": res_froi.value_bbox  if res_froi  else None,
                "zone_words":  summary_words,
            },
            "candidate": {
                "primary_roi": cand_zone.crop if cand_zone else None,
                "zone_image":  cand_zone.crop if cand_zone else None,
                "anchor_bbox": None,
                "zone_words":  [],
            },
        }

        adp = run_adaptive_extraction(fields_config)

        for fname, ar in adp.items():
            zone_texts[fname]       = ar.value or ""
            zone_confs[fname]       = ar.confidence
            adaptive_results[fname] = ar.to_dict()
            if not ar.found:
                failure_reasons[fname] = ar.failure_reason
            if ar.found:
                tag = f"adaptive:{ar.strategy_used.split(':')[0]}"
                if tag not in engines:
                    engines.append(tag)

        logger.info(
            "[layout_v2_pipeline] Adaptive: pct=%r cgpa=%r result=%r name=%r",
            zone_texts.get("percentage"), zone_texts.get("cgpa"),
            zone_texts.get("result"),     zone_texts.get("candidate"),
        )

    else:
        # Fallback: single-pass OCR if adaptive engine unavailable
        for field_name, roi_spec in roi_specs.items():
            use_easy = field_name in ("header", "candidate", "summary")
            text, conf, engine = _ocr_roi(roi_spec, use_easyocr=use_easy)
            zone_texts[field_name] = text
            zone_confs[field_name] = conf
            if engine not in engines:
                engines.append(engine)
            if debug and roi_spec.preprocessed is not None:
                pre_bgr = roi_spec.preprocessed
                if len(pre_bgr.shape) == 2:
                    pre_bgr = cv2.cvtColor(pre_bgr, cv2.COLOR_GRAY2BGR)
                debug_images[f"ocr_{field_name}"] = _save_debug_img(
                    pre_bgr, session_id, f"ocr_{field_name}"
                )

    # ── Stage 7: Spatial anchor mapping ──────────────────────────────────────
    anchor_fields: Dict[str, Optional[str]] = {}
    if summary_result and summary_result.debug_words:
        anchor_fields = map_anchor_fields(summary_result.debug_words)
        logger.info("[layout_v2_pipeline] Anchor-mapped: %s",
                    {k: v for k, v in anchor_fields.items() if v})

    # Promote summary_locator's color-channel / numeric OCR value into anchor_fields
    # (summary_result.percentage_roi.value_text is set by the summary locator
    #  color-channel pass even when anchor mapping finds nothing)
    if summary_result and summary_result.percentage_roi:
        locator_pct = summary_result.percentage_roi.value_text
        if locator_pct:
            try:
                fv = float(locator_pct)
                if fv >= 10.0:  # plausible percentage
                    anchor_fields["percentage"] = locator_pct
                    logger.info("[layout_v2_pipeline] Promoted locator pct into anchor_fields: %s",
                                locator_pct)
            except (ValueError, TypeError):
                pass


    if summary_result and summary_result.result_roi:
        locator_res = summary_result.result_roi.value_text
        if locator_res and not anchor_fields.get("result"):
            validated_res = _validate_result(locator_res)
            if validated_res:
                anchor_fields["result"] = validated_res

    # Result keyword scan: scan all available text sources for PASS/FAIL/ATKT
    if not anchor_fields.get("result"):
        _result_pattern = re.compile(r"\b(PASS|FAIL|ATKT|PASSED|FAILED|DISTINCTION)\b", re.I)

        # Sources in priority order
        _result_candidates = [summary_text, quick_text, zone_texts.get("summary", "")]

        # Direct summary zone OCR as final fallback (most reliable for this keyword)
        if summary_zone and summary_zone.crop is not None:
            try:
                # import pytesseract as _tess
                _sum_text = _tess.image_to_string(summary_zone.crop, config="--oem 3 --psm 6", lang="eng")
                _result_candidates.append(_sum_text)
            except Exception:
                pass

        for _src in _result_candidates:
            if not _src:
                continue
            _m = _result_pattern.search(_src)
            if _m:
                anchor_fields["result"] = _m.group(1).upper()
                logger.info("[layout_v2_pipeline] Result keyword scan: %s", anchor_fields["result"])
                break

    # Also run single-pass OCR for header/summary block text if not done above
    for fname in ("header", "summary"):
        if fname not in zone_texts and fname in roi_specs:
            text, _, engine = _ocr_roi(roi_specs[fname], use_easyocr=True)
            zone_texts[fname] = text
            if engine not in engines:
                engines.append(engine)

    # ── Stage 8: Raw field assembly ───────────────────────────────────────────
    # NOTE: adaptive engine may return a spurious value (e.g. '4.0' instead of
    # '75.17'). We validate each source and prefer the first that passes.

    def _best(*texts: str) -> str:
        return next((t for t in texts if t and t.strip()), "")

    def _best_pct(*sources: str) -> str:
        """Return first source that validates as a real percentage (>= 10.0 with decimal)."""
        for s in sources:
            if not s or not s.strip():
                continue
            v = _validate_percentage(s)
            if v:
                try:
                    fv = float(v)
                except ValueError:
                    continue
                # Reject academically implausible values (< 10% for a marksheet)
                if fv < 10.0:
                    continue
                # Reject 3-digit integers: total/max marks columns
                stripped = s.strip().rstrip("%").split()[0] if s.strip() else ""
                if re.fullmatch(r"\d{3}", stripped):
                    continue
                # Prefer decimal values (real percentages have decimals like 75.17)
                if "." in v:
                    return v
        # Second pass: accept any validated value >= 10.0
        for s in sources:
            v = _validate_percentage(s)
            if v:
                try:
                    if float(v) >= 10.0:
                        return v
                except ValueError:
                    pass
        return ""

    _pct_anchor   = anchor_fields.get("percentage") or ""
    _pct_adaptive = zone_texts.get("percentage", "")
    _pct_summary  = summary_text
    _pct_zone     = zone_texts.get("summary", "")

    # Anchor-first: word-level anchor mapping is more precise than crop OCR
    raw_pct = _best_pct(_pct_anchor, _pct_adaptive, _pct_summary, _pct_zone) or _best(
        _pct_anchor, _pct_adaptive, _pct_summary, _pct_zone
    )

    # CGPA: only use adaptive value if a CGPA label was actually found in summary
    # (prevents subject marks like '7.0' from being mistaken as CGPA)
    _cgpa_label_found = bool(
        anchor_fields.get("cgpa")
        or (summary_result and summary_result.cgpa_roi is not None
            and summary_result.cgpa_roi.label_bbox is not None)  # has a real label anchor
    )
    raw_cgpa = _best(
        anchor_fields.get("cgpa") or "",
        zone_texts.get("cgpa", "") if _cgpa_label_found else "",  # gate adaptive cgpa
        summary_text if _cgpa_label_found else "",
    )
    raw_result = _best(
        zone_texts.get("result", ""),
        anchor_fields.get("result") or "",
        summary_text,
        zone_texts.get("summary", ""),
    )
    raw_grade = _best(
        anchor_fields.get("grade_class") or "",
        summary_text,
    )
    raw_name = _best(
        zone_texts.get("candidate", ""),
        anchor_fields.get("candidate_name") or "",
    )

    # Direct candidate zone OCR fallback when adaptive returns nothing
    cz = zones.get("candidate")
    if not raw_name and cz and cz.crop is not None:
        try:
            # import pytesseract
            cand_text = pytesseract.image_to_string(cz.crop, config="--oem 3 --psm 6", lang="eng")
            zone_texts["candidate"] = cand_text  # also populate for ranker below
            raw_name = cand_text
            logger.info("[layout_v2_pipeline] Direct candidate OCR (%d chars)", len(cand_text))
        except Exception as _ce:
            logger.warning("[layout_v2_pipeline] Direct candidate OCR failed: %s", _ce)

    # Run adaptive name ranker for better denoising
    if zone_texts.get("candidate"):
        cz2 = zones.get("candidate")
        try:
            if _ADAPTIVE_AVAILABLE:
                ranked = extract_best_name(
                    zone_texts["candidate"],
                    zone_width=cz2.crop.shape[1] if cz2 and cz2.crop is not None else 0,
                )
            else:
                from app.academic_engine.adaptive.candidate_name_ranker import extract_best_name as _enb
                ranked = _enb(
                    zone_texts["candidate"],
                    zone_width=cz2.crop.shape[1] if cz2 and cz2.crop is not None else 0,
                )
            if ranked:
                raw_name = ranked
        except Exception as _re:
            logger.debug("[layout_v2_pipeline] Name ranker failed: %s", _re)

    raw_board = _best(zone_texts.get("header", ""))
    raw_year  = _best(
        anchor_fields.get("passing_year") or "",
        zone_texts.get("header", ""),
        zone_texts.get("candidate", ""),
    )

    logger.info(
        "[layout_v2_pipeline] Stage8: pct=%r (anchor=%r adaptive=%r)",
        raw_pct, _pct_anchor, _pct_adaptive,
    )

    # ── Stage 9: Validation ───────────────────────────────────────────────────
    percentage  = _validate_percentage(raw_pct)
    cgpa        = _validate_cgpa(raw_cgpa)
    result_val  = _validate_result(raw_result)
    grade_class = _validate_result(raw_grade) or re.sub(r"[^A-Za-z\s]", "", raw_grade).strip()[:30] or None
    name        = _validate_name(raw_name)
    year        = _validate_year(raw_year)

    board = None
    if raw_board:
        lines = [ln.strip() for ln in raw_board.splitlines() if len(ln.strip()) > 10]
        if lines:
            board = max(lines, key=len)[:120]

    # ── Stage 10: Priority selection ──────────────────────────────────────────
    priority = _select_primary_metric(percentage, cgpa, result_val, grade_class)

    # ── Stage 11: Build result ─────────────────────────────────────────────────
    elapsed_ms     = round((time.time() - t0) * 1000, 1)
    zones_detected = [n for n, z in zones.items() if z.enabled and z.crop is not None]
    active_failures = {f: r for f, r in failure_reasons.items() if r}
    adp_metrics    = get_adaptive_metrics() if _ADAPTIVE_AVAILABLE else {}

    logger.info(
        "[layout_v2_pipeline] ══ Done %.0fms — pct=%s cgpa=%s result=%s name=%s ══",
        elapsed_ms,
        priority.get("percentage"), priority.get("cgpa"),
        priority.get("result"),     name,
    )

    return {
        "candidate_name":   name,
        "board_university": board,
        "passing_year":     year,
        "percentage":       priority.get("percentage"),
        "cgpa":             priority.get("cgpa"),
        "grade_class":      priority.get("grade_class"),
        "result":           priority.get("result"),
        "_layout_meta": {
            "layout_class":          variant.layout_class,
            "table_detected":        table_detected,
            "zones_detected":        zones_detected,
            "summary_anchors_found": bool(summary_result and summary_result.found),
            "ocr_engines":           list(dict.fromkeys(engines)),
            "elapsed_ms":            elapsed_ms,
            "debug_session":         session_id,
            "debug_images":          debug_images if debug else {},
            "zone_texts":            zone_texts,
            "anchor_fields":         {k: v for k, v in anchor_fields.items() if v},
            # Adaptive engine debug data (for Visual OCR Lab)
            "adaptive_results":      adaptive_results,
            "failure_reasons":       active_failures,
            "adaptive_metrics":      adp_metrics,
            "adaptive_engine":       _ADAPTIVE_AVAILABLE,
        },
    }
