import uuid
import numpy as np
import cv2

from .preprocess.image_variants import ImagePreprocessor
from .ocr.ensemble import OCREnsemble
from .ocr.repair import OCRRepairLayer
from .graph.builder import GraphBuilder
from .semantics.anchors import SemanticAnchorEngine
from .parsers.name_parser import NameParser
from .parsers.metric_parser import MetricParser
from .detection.classifier import DocumentClassifier
from .confidence.scorer import ConfidenceScorer
from .debug.visualizer import DebugVisualizer

class UniversalAcademicEngine:
    def __init__(self):
        self.preprocessor = ImagePreprocessor()
        self.ocr_ensemble = OCREnsemble()
        self.ocr_repair = OCRRepairLayer()
        self.graph_builder = GraphBuilder()
        self.anchor_engine = SemanticAnchorEngine()
        self.name_parser = NameParser()
        self.metric_parser = MetricParser()
        self.classifier = DocumentClassifier()
        self.scorer = ConfidenceScorer()
        self.visualizer = DebugVisualizer()

    def extract(self, image_bytes: bytes) -> dict:
        session_id = str(uuid.uuid4())
        
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Invalid image")
            
        variants = self.preprocessor.generate_variants(img)
        tokens = self.ocr_ensemble.run(variants)
        tokens = self.ocr_repair.repair(tokens)
        
        graph = self.graph_builder.build(tokens)
        anchors = self.anchor_engine.detect(tokens)
        
        doc_type = self.classifier.classify(tokens)
        
        name_res = self.name_parser.parse("CANDIDATE_NAME", tokens, anchors, graph)
        mother_res = self.name_parser.parse("MOTHER_NAME", tokens, anchors, graph)
        father_res = self.name_parser.parse("FATHER_NAME", tokens, anchors, graph)
        
        pct_res = self.metric_parser.parse("PERCENTAGE", tokens, anchors, graph)
        cgpa_res = self.metric_parser.parse("CGPA", tokens, anchors, graph)
        
        def _reconstruct_lines(tks):
            if not tks: return ""
            tks.sort(key=lambda t: (t.y1, t.x1))
            lines = []
            current_line = []
            last_y = -1
            avg_h = sum(t.y2 - t.y1 for t in tks) / len(tks) if tks else 10
            for t in tks:
                if last_y == -1 or abs(t.y1 - last_y) < avg_h * 0.5:
                    current_line.append(t)
                else:
                    current_line.sort(key=lambda x: x.x1)
                    lines.append(" ".join(x.text for x in current_line))
                    current_line = [t]
                last_y = t.y1
            if current_line:
                current_line.sort(key=lambda x: x.x1)
                lines.append(" ".join(x.text for x in current_line))
            return "\n".join(lines)
            
        result_payload = {
            "document_type": doc_type,
            "candidate_name": name_res.dict() if hasattr(name_res, "dict") else name_res,
            "mother_name": mother_res.dict() if hasattr(mother_res, "dict") else mother_res,
            "father_name": father_res.dict() if hasattr(father_res, "dict") else father_res,
            "percentage": pct_res.dict() if hasattr(pct_res, "dict") else pct_res,
            "cgpa": cgpa_res.dict() if hasattr(cgpa_res, "dict") else cgpa_res,
            "raw_text": _reconstruct_lines(tokens),
            "subjects": [],
            "metadata": {"session_id": session_id}
        }
        
        # Step 7: Table Understanding
        from .segmentation.tables import TableParser
        table_parser = TableParser()
        tables = table_parser.detect_tables(variants["binary"], tokens)
        
        doc_conf = self.scorer.score_document({
            "candidate_name": {"confidence": name_res.confidence},
            "percentage": {"confidence": pct_res.confidence},
            "cgpa": {"confidence": cgpa_res.confidence},
            "document_type": {"confidence": 1.0 if doc_type != "UNKNOWN_ACADEMIC_DOCUMENT" else 0.0}
        })
        
        # Step 11: Fallback Strategy
        if doc_conf < 0.4:
            # Low confidence - trigger secondary fallback ensemble
            fallback_tokens = self.ocr_ensemble.run({"denoised": variants["denoised"]})
            fallback_tokens = self.ocr_repair.repair(fallback_tokens)
            fallback_anchors = self.anchor_engine.detect(fallback_tokens)
            
            # Re-parse high value fields
            fallback_name = self.name_parser.parse("CANDIDATE_NAME", fallback_tokens, fallback_anchors, graph)
            if fallback_name.confidence > name_res.confidence:
                name_res = fallback_name
                result_payload["candidate_name"] = name_res.dict()
                
            fallback_pct = self.metric_parser.parse("PERCENTAGE", fallback_tokens, fallback_anchors, graph)
            if fallback_pct.confidence > pct_res.confidence:
                pct_res = fallback_pct
                result_payload["percentage"] = pct_res.dict()
                
            # Recalculate confidence
            doc_conf = self.scorer.score_document({
                "candidate_name": {"confidence": name_res.confidence},
                "percentage": {"confidence": pct_res.confidence},
                "cgpa": {"confidence": cgpa_res.confidence},
                "document_type": {"confidence": 1.0 if doc_type != "UNKNOWN_ACADEMIC_DOCUMENT" else 0.0}
            })

        result_payload["tables"] = tables
        result_payload["document_confidence"] = doc_conf
        
        self.visualizer.save(session_id, result_payload)
        
        return result_payload
