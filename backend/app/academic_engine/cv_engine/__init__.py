"""
cv_engine
=========
Computer Vision foundation for academic document intelligence.

This module provides true CV-based document understanding:
- Document boundary detection
- Perspective correction
- Visual structure analysis
- Semantic layout graphs
- Adaptive ROI generation
- Text region segmentation
- Visual confidence scoring
"""

from .smart_document_detector import SmartDocumentDetector, detect_document_boundary
from .perspective_alignment import PerspectiveAligner, align_document
from .document_structure_analyzer import DocumentStructureAnalyzer, analyze_structure
from .semantic_layout_graph import SemanticLayoutGraph, build_layout_graph
from .adaptive_roi_builder import AdaptiveROIBuilder, build_dynamic_rois
from .visual_anchor_detector import VisualAnchorDetector, detect_anchors
from .text_region_segmenter import TextRegionSegmenter, segment_text_regions
from .visual_confidence_engine import VisualConfidenceEngine, compute_confidence
from .cv_pipeline import CVPipeline, process_document

__all__ = [
    "SmartDocumentDetector",
    "detect_document_boundary",
    "PerspectiveAligner",
    "align_document",
    "DocumentStructureAnalyzer",
    "analyze_structure",
    "SemanticLayoutGraph",
    "build_layout_graph",
    "AdaptiveROIBuilder",
    "build_dynamic_rois",
    "VisualAnchorDetector",
    "detect_anchors",
    "TextRegionSegmenter",
    "segment_text_regions",
    "VisualConfidenceEngine",
    "compute_confidence",
    "CVPipeline",
    "process_document",
]
