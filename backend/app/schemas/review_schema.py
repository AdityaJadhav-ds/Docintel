"""
app/schemas/review_schema.py — Pydantic schemas for review system
=================================================================
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ApproveRequest(BaseModel):
    reviewer_id: str = Field(..., description="Reviewer user ID / auth UID")
    notes:       Optional[str] = Field(None, description="Optional reviewer note")


class RejectRequest(BaseModel):
    reviewer_id: str
    reason:      Optional[str] = None


class CorrectionField(BaseModel):
    field:     str             # name | dob | aadhaar_number | pan_number
    new_value: Optional[str]


class CorrectRequest(BaseModel):
    reviewer_id: str
    corrections: Dict[str, Optional[str]]   # {field_name: corrected_value}
    notes:       Optional[str] = None


class ReprocessRequest(BaseModel):
    reviewer_id: str
    reason:      Optional[str] = None


class ClaimRequest(BaseModel):
    reviewer_id: str


class BulkApproveRequest(BaseModel):
    review_ids:  List[str]
    reviewer_id: str


class BulkRejectRequest(BaseModel):
    review_ids:  List[str]
    reviewer_id: str
    reason:      Optional[str] = None


class QueueFilterParams(BaseModel):
    status:    Optional[str] = None
    doc_type:  Optional[str] = None
    decision:  Optional[str] = None
    priority:  Optional[int] = None
    page:      int = 1
    page_size: int = 20
    sort_by:   str = "priority"
    sort_desc: bool = False
