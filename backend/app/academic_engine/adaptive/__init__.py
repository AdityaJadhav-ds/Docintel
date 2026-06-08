"""
academic_engine/adaptive/__init__.py
=====================================
Self-Healing Adaptive ROI Extraction Engine.

Modules:
  roi_retry_engine     — Multi-attempt ROI extraction with auto-escalation
  adaptive_cropper     — Multi-strategy crop generation (expand/shift/contour)
  fallback_strategies  — Spatial fallbacks when primary anchor fails
  confidence_recovery  — OCR text repair (7517→75.17, 8S.4→85.4, etc.)
  roi_optimizer        — Multi-preprocessing ensemble + OCR voting
  candidate_name_ranker — Denoised candidate name selection from OCR candidates

ISOLATION: Zero imports from Aadhaar / PAN / KYC modules.
"""

__version__ = "1.0.0"
