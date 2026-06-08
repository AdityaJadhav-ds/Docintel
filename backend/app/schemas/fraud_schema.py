"""
app/schemas/fraud_schema.py — Pydantic schemas for fraud API
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class FraudAnalyzeRequest(BaseModel):
    user_id:     int
    document_id: Optional[int] = None
    doc_type:    str = "unknown"


class FraudRecheckRequest(BaseModel):
    fraud_id: str
    reason:   Optional[str] = None
