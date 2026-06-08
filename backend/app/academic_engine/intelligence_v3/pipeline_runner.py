import os
import json
from datetime import datetime

from .input_normalizer import InputNormalizer
from .document_detector import DocumentDetector
from .geometry_corrector import GeometryCorrector
from .text_region_segmenter import TextRegionSegmenter
from .ocr_ensemble_engine import OCREnsembleEngine
from .ocr_cleaner import OCRCleaner
from .document_structure_engine import DocumentStructureEngine
from .ocr_relationship_graph import OCRRelationshipGraph
from .semantic_anchor_engine import SemanticAnchorEngine
from .universal_field_resolver import UniversalFieldResolver
from .candidate_name_engine import CandidateNameEngine
from .percentage_reasoner import PercentageReasoner
from .cgpa_reasoner import CGPAReasoner
from .result_reasoner import ResultReasoner
from .board_detector import BoardDetector
from .confidence_engine import ConfidenceEngine

class IntelligencePipeline:
    def __init__(self):
        self.normalizer = InputNormalizer()
        self.detector = DocumentDetector()
        self.corrector = GeometryCorrector()
        self.segmenter = TextRegionSegmenter()
        self.ocr_engine = OCREnsembleEngine()
        self.cleaner = OCRCleaner()
        self.structure_engine = DocumentStructureEngine()
        self.graph_engine = OCRRelationshipGraph()
        self.anchor_engine = SemanticAnchorEngine()
        self.resolver = UniversalFieldResolver()
        self.confidence_engine = ConfidenceEngine()
        
        self.field_engines = {
            "name": CandidateNameEngine(),
            "percentage": PercentageReasoner(),
            "cgpa": CGPAReasoner(),
            "result": ResultReasoner(),
            "board": BoardDetector()
        }

    def process(self, image_bytes: bytes, session_id: str = None) -> dict:
        if not session_id:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            
        img = self.normalizer.normalize(image_bytes)
        cropped = self.detector.detect_document(img)
        deskewed = self.corrector.correct(cropped)
        regions = self.segmenter.segment(deskewed)
        nodes = self.ocr_engine.run_ensemble(deskewed, regions)
        clean_nodes = self.cleaner.clean(nodes)
        structured_nodes = self.structure_engine.analyze(clean_nodes)
        graph = self.graph_engine.build_graph(structured_nodes)
        anchors = self.anchor_engine.detect_anchors(structured_nodes)
        results = self.resolver.resolve(structured_nodes, anchors, graph, self.field_engines)
        confidence = self.confidence_engine.calculate_confidence(results, structured_nodes)
        
        final_output = {
            "session_id": session_id,
            "confidence": confidence,
            "data": {
                "candidate_name": results.get("candidate_name"),
                "result": results.get("result"),
                "board_university": results.get("board")
            }
        }
        
        if results.get("cgpa"):
            final_output["data"]["cgpa"] = results.get("cgpa")
        elif results.get("percentage"):
            final_output["data"]["percentage"] = results.get("percentage")
            
        self._save_debug_data(session_id, final_output)
        
        return final_output

    def _save_debug_data(self, session_id: str, data: dict):
        debug_dir = f"academic_debug/{session_id}"
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "9_final_selection.json"), "w") as f:
            json.dump(data, f, indent=4)
