"""
app/api/fraud_routes.py — Fraud detection & risk intelligence endpoints
=======================================================================
"""

from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
import io

from app.core.logger import logger
from app.fraud.fraud_engine import (
    analyze_document, get_fraud_analysis,
    get_user_fraud_history, get_high_risk_cases, get_fraud_statistics,
)
from app.fraud.duplicate_detector import find_id_duplicates
from app.schemas.fraud_schema import FraudAnalyzeRequest, FraudRecheckRequest
from app.core.supabase_client import get_supabase

router = APIRouter(prefix="/fraud", tags=["Fraud Detection"])


# ── Analyze uploaded document ─────────────────────────────────────────────────

@router.post("/analyze")
async def fraud_analyze(
    file:        UploadFile = File(...),
    user_id:     int        = Form(...),
    document_id: Optional[int] = Form(None),
    doc_type:    str        = Form("unknown"),
    ocr_confidence: float   = Form(1.0),
):
    """
    Run full fraud analysis on an uploaded document image.
    Returns risk score, quality score, tamper flags, duplicate status.
    """
    try:
        contents = await file.read()
        image_input = io.BytesIO(contents)
        result = analyze_document(
            image_input    = image_input,
            user_id        = user_id,
            doc_type       = doc_type,
            document_id    = document_id,
            ocr_confidence = ocr_confidence,
        )
        return {"success": True, **result}
    except Exception as exc:
        logger.error("[fraud_routes] /analyze error: %s", exc)
        raise HTTPException(500, f"Fraud analysis failed: {exc}")


# ── Get stored fraud analysis ─────────────────────────────────────────────────

@router.get("/analysis/{fraud_id}")
def get_analysis(fraud_id: str):
    """Fetch a stored fraud analysis record by ID."""
    record = get_fraud_analysis(fraud_id)
    if not record:
        raise HTTPException(404, "Fraud analysis record not found.")
    return {"success": True, "analysis": record}


@router.get("/user/{user_id}")
def user_fraud_history(user_id: int):
    """All fraud analyses for a user."""
    history = get_user_fraud_history(user_id)
    return {"success": True, "user_id": user_id, "history": history, "total": len(history)}


# ── Duplicates ────────────────────────────────────────────────────────────────

@router.get("/duplicates")
def get_duplicates(
    limit: int = Query(100, le=500),
    page:  int = Query(1, ge=1),
):
    """Fetch all recorded duplicate identity matches."""
    try:
        sb  = get_supabase()
        offset = (page - 1) * limit
        res = (
            sb.table("duplicate_matches")
            .select("*", count="exact")
            .order("flagged_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return {
            "success": True,
            "items":   res.data or [],
            "total":   res.count or 0,
            "page":    page,
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── High-risk cases ───────────────────────────────────────────────────────────

@router.get("/high-risk")
def high_risk_cases(
    min_score: int = Query(50, ge=0, le=100),
    limit:     int = Query(100, le=500),
):
    """Fetch all documents with risk_score >= min_score."""
    cases = get_high_risk_cases(min_score=min_score, limit=limit)
    return {"success": True, "cases": cases, "total": len(cases), "min_score": min_score}


# ── Statistics ────────────────────────────────────────────────────────────────

@router.get("/statistics")
def fraud_statistics():
    """Aggregate fraud metrics for dashboard."""
    stats = get_fraud_statistics()
    return {"success": True, "statistics": stats}


# ── Recheck (trigger re-analysis) ─────────────────────────────────────────────

@router.post("/recheck")
async def recheck(
    file:    UploadFile = File(...),
    user_id: int        = Form(...),
    doc_type: str       = Form("unknown"),
    reason:  Optional[str] = Form(None),
):
    """
    Re-run fraud analysis (e.g., after reviewer flags suspicious document).
    Creates a new fraud_analysis record — never overwrites old one.
    """
    try:
        contents    = await file.read()
        image_input = io.BytesIO(contents)
        result = analyze_document(
            image_input = image_input,
            user_id     = user_id,
            doc_type    = doc_type,
        )
        logger.info("[fraud_routes] Recheck for user_id=%s reason=%s → risk=%s",
                    user_id, reason, result.get("risk_level"))
        return {"success": True, "recheck": True, **result}
    except Exception as exc:
        raise HTTPException(500, f"Recheck failed: {exc}")


# ── ID duplicate check (without image) ────────────────────────────────────────

@router.get("/check-id")
def check_id_duplicates(
    user_id:        int           = Query(...),
    aadhaar_number: Optional[str] = Query(None),
    pan_number:     Optional[str] = Query(None),
):
    """
    Check if a specific Aadhaar or PAN number is used by another user.
    Does not require an image upload.
    """
    matches = find_id_duplicates(user_id, aadhaar_number, pan_number)
    return {
        "success":            True,
        "duplicate_detected": bool(matches),
        "matches":            matches,
        "total":              len(matches),
    }
