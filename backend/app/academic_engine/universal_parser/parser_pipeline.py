import numpy as np
import logging
from typing import Dict, Any

from .semantic_document_parser import build_ocr_graph
from .universal_field_resolver import (
    extract_percentage, extract_cgpa, extract_result,
    extract_candidate_name, extract_passing_year, extract_board_university
)
from .extraction_reasoner import clear_reasoning, get_reasoning

logger = logging.getLogger(__name__)

def run_universal_parser(image: np.ndarray) -> Dict[str, Any]:
    """
    Main entry point for the Universal Semantic Parser.
    Replaces spatial_v3 coordinate-based extraction.
    """
    logger.info("[Universal Parser] Starting extraction...")
    clear_reasoning()
    
    # Step 1 & 2: Build OCR map and line reconstruction
    graph = build_ocr_graph(image)
    logger.info(f"[Universal Parser] Graph built: {len(graph.words)} words, {len(graph.lines)} lines.")
    
    # Step 3, 4, 5: Universal Field Resolution via Relationships
    extracted = {
        "candidate_name": extract_candidate_name(graph),
        "percentage": extract_percentage(graph),
        "cgpa": extract_cgpa(graph),
        "result": extract_result(graph),
        "passing_year": extract_passing_year(graph),
        "board_university": extract_board_university(graph)
    }
    
    # Add reasoning metadata for debug
    extracted["_parser_reasoning"] = get_reasoning()
    extracted["raw_text"] = "\n".join(l.text for l in graph.lines)
    
    return extracted
