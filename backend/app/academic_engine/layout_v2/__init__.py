"""
app/academic_engine/layout_v2/__init__.py
==========================================
Academic Layout Intelligence Engine v2.

Replaces fraction-based zone slicing with CONTENT-ADAPTIVE spatial analysis.

Modules:
  zone_segmenter      — Adaptive document zone detection (A–E)
  roi_detector        — Per-field ROI extraction with sub-zone precision
  table_detector      — Identify and mask subject-table noise
  summary_locator     — Pinpoint the percentage / CGPA / result block
  anchor_mapper       — Label → nearest value spatial mapping
  layout_classifier   — Classify layout variant (SSC / HSC / Degree / Certificate)
  spatial_relationships — Geometric helpers (proximity, alignment, containment)

ISOLATION: Zero imports from Aadhaar / PAN / KYC modules.
"""

__version__ = "2.0.0"
