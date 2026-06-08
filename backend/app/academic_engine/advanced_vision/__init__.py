from .classifier import classify_document_quality
from .geometry import multi_contour_detection, curved_page_flattening
from .illumination import remove_glare, remove_shadows
from .enhancement import super_resolution, recover_blur, color_normalization
from .text_and_tables import detect_text_regions, preserve_tables, multi_ocr_zone_strategy
from .optimizer import ocr_readiness_optimizer
from .heatmaps import generate_debug_heatmaps
from .pipeline import AdvancedVisionPipeline

__all__ = [
    "classify_document_quality",
    "multi_contour_detection",
    "curved_page_flattening",
    "remove_glare",
    "remove_shadows",
    "super_resolution",
    "recover_blur",
    "color_normalization",
    "detect_text_regions",
    "preserve_tables",
    "multi_ocr_zone_strategy",
    "ocr_readiness_optimizer",
    "generate_debug_heatmaps",
    "AdvancedVisionPipeline"
]
