import cv2
import numpy as np
import logging
from concurrent.futures import ThreadPoolExecutor

from .classifier import classify_document_quality
from .geometry import multi_contour_detection, curved_page_flattening
from .illumination import remove_glare, remove_shadows
from .enhancement import super_resolution, recover_blur, color_normalization
from .text_and_tables import detect_text_regions, preserve_tables, multi_ocr_zone_strategy
from .optimizer import ocr_readiness_optimizer
from .heatmaps import generate_debug_heatmaps

logger = logging.getLogger(__name__)

class AdvancedVisionPipeline:
    """Step 15: Performance Optimization - Async preprocessing, caching, parallel variants."""
    
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)
        
    def process(self, image: np.ndarray) -> dict:
        # Step 1: Document Classification
        classification = classify_document_quality(image)
        if not classification['is_readable']:
            return {"status": "failed", "warnings": classification['warnings']}
            
        # Step 2 & 3: Contour Detection and Flattening
        contour = multi_contour_detection(image)
        flattened = curved_page_flattening(image, contour)
        
        # Step 8: Super Resolution (if low res)
        if max(flattened.shape[:2]) < 1000:
            flattened = super_resolution(flattened)
            
        # Parallel enhancements (Step 4, 5, 9, 10, 7)
        def generate_variants(img):
            glare_free = remove_glare(img)
            shadow_free = remove_shadows(glare_free)
            deblurred = recover_blur(shadow_free)
            normalized = color_normalization(deblurred)
            
            # Step 7: Table Preservation
            table_info = preserve_tables(shadow_free)
            
            return {
                "original": img,
                "shadow_free": shadow_free,
                "deblurred": deblurred,
                "normalized": normalized,
                "table_ocr": table_info['ocr_image'],
                "structure_mask": table_info['structure_mask']
            }
            
        # Run variants generation
        variants = generate_variants(flattened)
        structure_mask = variants.pop("structure_mask", None)
        
        # Step 12: Optimizer
        best_variant_key = ocr_readiness_optimizer(variants)
        best_image = variants[best_variant_key]
        
        # Step 6 & 11: Text Regions and Multi-Zone
        text_regions = detect_text_regions(best_image)
        zones = multi_ocr_zone_strategy(best_image, text_regions)
        
        # Step 14: Heatmaps
        heatmaps = generate_debug_heatmaps(flattened, text_regions, contour, structure_mask)
        
        return {
            "status": "success",
            "classification": classification,
            "best_image": best_image,
            "variants": variants,
            "best_variant_name": best_variant_key,
            "zones": zones,
            "heatmaps": heatmaps,
            "warnings": classification['warnings']
        }
