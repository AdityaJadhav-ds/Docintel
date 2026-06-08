import numpy as np

from .region_dispatcher import RegionDispatcher
from .fusion_ranker import FusionRanker
from .text_voting import TextVoter
from .ocr_normalizer import OCRNormalizer
from .confidence_engine import ConfidenceEngine
from .debug_visualizer import DebugVisualizer

class OCRFusionPipeline:
    """Main Orchestrator for the Multi-Engine OCR Fusion Pipeline."""
    
    def __init__(self):
        self.dispatcher = RegionDispatcher()
        self.ranker = FusionRanker()
        self.voter = TextVoter()
        self.normalizer = OCRNormalizer()
        self.confidence_engine = ConfidenceEngine()
        self.visualizer = DebugVisualizer()
        
    def process(self, original_image: np.ndarray, regions: dict, global_lang="eng+mar") -> dict:
        """
        Process the image with multiple OCR engines per region.
        regions format: { "header": [(x,y,w,h), ...], "student_info": [...], ... }
        """
        final_regions = []
        all_words = []
        engine_stats = {"tesseract": 0, "easyocr": 0, "paddleocr": 0}
        
        # Step 1: Region Based OCR loop
        for region_name, bboxes in regions.items():
            for bbox in bboxes:
                x, y, w, h = bbox
                # Safety check
                if w <= 0 or h <= 0 or x < 0 or y < 0:
                    continue
                    
                region_roi = original_image[y:y+h, x:x+w]
                
                # Step 2 & 3: Dispatch to all engines with multi preprocess variants
                raw_candidates = self.dispatcher.dispatch_region(region_roi, region_name, lang=global_lang)
                
                # Group overlapping boxes across engines
                groups = self.ranker.group_candidates(raw_candidates)
                
                fused_region_words = []
                rejected_candidates = []
                
                # Step 6 & 7: Voting (Text & Numeric) and Step 5: Normalization
                for group in groups:
                    best_text_raw = self.voter.vote(group)
                    normalized_text = self.normalizer.normalize(best_text_raw)
                    
                    # Step 4 & 10: Word level confidence and structure
                    if normalized_text:
                        word_conf = self.confidence_engine.compute_word_confidence(group, best_text_raw)
                        
                        # Use average bbox of the group for the final word
                        avg_x = int(sum(c['bbox'][0] for c in group) / len(group))
                        avg_y = int(sum(c['bbox'][1] for c in group) / len(group))
                        avg_w = int(sum(c['bbox'][2] for c in group) / len(group))
                        avg_h = int(sum(c['bbox'][3] for c in group) / len(group))
                        
                        # Add global coordinate offset
                        global_bbox = (avg_x + x, avg_y + y, avg_w, avg_h)
                        
                        fused_word = {
                            "text": normalized_text,
                            "confidence": word_conf,
                            "bbox": global_bbox
                        }
                        fused_region_words.append(fused_word)
                        all_words.append(fused_word)
                        
                        # Update usage stats
                        for c in group:
                            engine_stats[c['engine']] += 1
                    else:
                        # For debug visualizations
                        rejected_candidates.extend(group)
                        
                # Region level output stats
                region_conf = self.confidence_engine.compute_region_confidence(fused_region_words)
                final_regions.append({
                    "type": region_name,
                    "bbox": bbox,
                    "words": fused_region_words,
                    "confidence": region_conf,
                    "rejected_count": len(rejected_candidates)
                })
                
        # Final merged text (in rough reading order: top-bottom, left-right)
        all_words.sort(key=lambda w: (w['bbox'][1] // 15, w['bbox'][0]))
        merged_text = " ".join(w['text'] for w in all_words)
        
        # Step 12: Final OCR Response format
        overall_conf = self.confidence_engine.compute_region_confidence(all_words)
        
        return {
            "regions": final_regions,
            "merged_text": merged_text,
            "words": all_words,
            "confidence_map": {
                "overall": overall_conf
            },
            "engine_stats": engine_stats
        }
