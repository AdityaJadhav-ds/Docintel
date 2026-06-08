"""
app/academic/schemas.py — Pydantic data models for academic documents
======================================================================
Strongly-typed schemas for SSC / HSC / Degree extracted data.
All fields are Optional to gracefully handle partial extractions.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Subject mark entry ────────────────────────────────────────────────────────

class SubjectMark(BaseModel):
    subject:        str
    marks_obtained: Optional[float] = None
    marks_total:    Optional[float] = None
    grade:          Optional[str]  = None
    credits:        Optional[float] = None
    grade_points:   Optional[float] = None
    is_passed:      Optional[bool] = None


# ── SSC (10th) schema ─────────────────────────────────────────────────────────

class SSCData(BaseModel):
    document_type:   str = "ssc"
    candidate_name:  Optional[str]   = None
    mother_name:     Optional[str]   = None
    seat_number:     Optional[str]   = None
    certificate_no:  Optional[str]   = None
    board:           Optional[str]   = None
    school_number:   Optional[str]   = None
    passing_year:    Optional[int]   = None
    total_marks:     Optional[float] = None
    obtained_marks:  Optional[float] = None
    percentage:      Optional[float] = None
    grade:           Optional[str]   = None
    division:        Optional[str]   = None
    result:          Optional[str]   = None
    dob:             Optional[str]   = None
    subjects:        List[SubjectMark] = Field(default_factory=list)


# ── HSC (12th) schema ─────────────────────────────────────────────────────────

class HSCData(BaseModel):
    document_type:   str = "hsc"
    candidate_name:  Optional[str]   = None
    mother_name:     Optional[str]   = None
    seat_number:     Optional[str]   = None
    certificate_no:  Optional[str]   = None
    board:           Optional[str]   = None
    school_number:   Optional[str]   = None
    stream:          Optional[str]   = None
    passing_year:    Optional[int]   = None
    total_marks:     Optional[float] = None
    obtained_marks:  Optional[float] = None
    percentage:      Optional[float] = None
    grade:           Optional[str]   = None
    division:        Optional[str]   = None
    result:          Optional[str]   = None
    dob:             Optional[str]   = None
    subjects:        List[SubjectMark] = Field(default_factory=list)


# ── Semester entry for Degree ─────────────────────────────────────────────────

class SemesterData(BaseModel):
    semester:        int
    sgpa:            Optional[float] = None
    credits:         Optional[float] = None
    marks_obtained:  Optional[float] = None
    marks_total:     Optional[float] = None
    result:          Optional[str]   = None
    subjects:        List[SubjectMark] = Field(default_factory=list)


# ── Degree / University schema ────────────────────────────────────────────────

class DegreeData(BaseModel):
    document_type:    str = "degree"
    student_name:     Optional[str]   = None
    prn:              Optional[str]   = None
    seat_number:      Optional[str]   = None
    enrollment_no:    Optional[str]   = None
    university:       Optional[str]   = None
    degree_name:      Optional[str]   = None
    course_name:      Optional[str]   = None
    passing_year:     Optional[int]   = None
    cgpa:             Optional[float] = None
    aggregate_percentage: Optional[float] = None
    result_class:     Optional[str]   = None
    grade:            Optional[str]   = None
    semesters:        List[SemesterData] = Field(default_factory=list)
    all_subjects:     List[SubjectMark]  = Field(default_factory=list)


# ── Detection result ──────────────────────────────────────────────────────────

class DetectionResult(BaseModel):
    document_type: str        # ssc | hsc | degree | unknown
    confidence:    float      # 0-100
    reason:        str
    keyword_hits:  List[str] = Field(default_factory=list)


# ── Full analysis result ──────────────────────────────────────────────────────

class AcademicAnalysisResult(BaseModel):
    status:       str  # success | partial | failed
    document_id:  Optional[str]  = None
    detection:    Optional[DetectionResult] = None
    extracted:    Optional[Dict[str, Any]]  = None
    raw_text:     Optional[str]  = None
    confidence:   float = 0.0
    warnings:     List[str] = Field(default_factory=list)
    errors:       List[str] = Field(default_factory=list)


# ── API request/response ──────────────────────────────────────────────────────

class AcademicAnalyzeResponse(BaseModel):
    status:      str
    document_id: str
    doc_type:    str
    confidence:  float
    detection:   Dict[str, Any]
    extracted:   Dict[str, Any]
    warnings:    List[str]
    raw_text_preview: str
