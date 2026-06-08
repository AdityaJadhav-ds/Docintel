import re
from typing import Optional, Tuple
from .relationship_graph import DocumentGraph
from .keyword_anchor_engine import find_anchors
from .semantic_validators import is_valid_percentage, clean_percentage, is_valid_cgpa, is_valid_name
from .extraction_reasoner import track_reasoning

def extract_percentage(graph: DocumentGraph) -> Optional[str]:
    lines = find_anchors(graph, "percentage")
    candidate_pool = []
    rejected = []
    
    for line in lines:
        for word in line.words:
            # Check same line right
            right_word = graph.find_nearest_right(word)
            if right_word:
                candidate_pool.append(right_word.text)
                
            # Check below
            below_word = graph.find_nearest_below(word)
            if below_word:
                candidate_pool.append(below_word.text)
                
    # Fallback: search entire graph for "%" or something looking like a percentage
    if not candidate_pool:
        for w in graph.words:
            if "%" in w.text or clean_percentage(w.text):
                candidate_pool.append(w.text)

    best_candidate = None
    for cand in candidate_pool:
        cleaned = clean_percentage(cand)
        if cleaned:
            best_candidate = cleaned
            break
        else:
            rejected.append(cand)
            
    track_reasoning("percentage", "percentage_anchors", candidate_pool, rejected, best_candidate)
    return best_candidate

def extract_cgpa(graph: DocumentGraph) -> Optional[str]:
    lines = find_anchors(graph, "cgpa")
    candidate_pool = []
    rejected = []
    
    for line in lines:
        for word in line.words:
            right_word = graph.find_nearest_right(word)
            if right_word:
                candidate_pool.append(right_word.text)
            below_word = graph.find_nearest_below(word)
            if below_word:
                candidate_pool.append(below_word.text)
                
    best_candidate = None
    for cand in candidate_pool:
        clean = re.sub(r'[^\d.]', '', cand)
        if is_valid_cgpa(clean):
            best_candidate = clean
            break
        else:
            rejected.append(cand)
            
    track_reasoning("cgpa", "cgpa_anchors", candidate_pool, rejected, best_candidate)
    return best_candidate

def extract_result(graph: DocumentGraph) -> Optional[str]:
    # Look for specific result keywords
    valid_results = ["PASS", "FAIL", "DISTINCTION", "FIRST CLASS", "SECOND CLASS"]
    
    # First search via anchors
    lines = find_anchors(graph, "result")
    for line in lines:
        for word in line.words:
            right_word = graph.find_nearest_right(word)
            if right_word and right_word.text.upper() in valid_results:
                return right_word.text.upper()
            below_word = graph.find_nearest_below(word)
            if below_word and below_word.text.upper() in valid_results:
                return below_word.text.upper()
                
    # Fallback search anywhere
    for w in graph.words:
        upper_text = w.text.upper()
        for res in valid_results:
            if res in upper_text:
                return res
                
    return None

def extract_candidate_name(graph: DocumentGraph) -> Optional[str]:
    lines = find_anchors(graph, "name")
    candidate_pool = []
    rejected = []
    
    for line in lines:
        # Often name is on the same line after the anchor or the line below
        # For "candidate name : X Y Z", check the rest of the line
        text_lower = line.text.lower()
        if ":" in line.text:
            parts = line.text.split(":")
            if len(parts) > 1 and parts[1].strip():
                candidate_pool.append(parts[1].strip())
        
        # Check nearest right
        if line.words:
            right_word = graph.find_nearest_right(line.words[-1])
            if right_word:
                # If it's a single word, maybe we need the whole line containing it
                # For simplicity, let's grab the line of the right_word
                target_line = next((l for l in graph.lines if right_word in l.words), None)
                if target_line:
                    candidate_pool.append(target_line.text)

        # Check line below
        idx = graph.lines.index(line)
        if idx + 1 < len(graph.lines):
            below_line = graph.lines[idx+1]
            candidate_pool.append(below_line.text)
            
    best_candidate = None
    for cand in candidate_pool:
        if is_valid_name(cand):
            best_candidate = cand
            break
        else:
            rejected.append(cand)
            
    track_reasoning("candidate_name", "name_anchors", candidate_pool, rejected, best_candidate)
    return best_candidate

def extract_passing_year(graph: DocumentGraph) -> Optional[str]:
    # Regex for YYYY or Mon-YYYY
    year_pattern = re.compile(r'\b(19|20)\d{2}\b')
    lines = find_anchors(graph, "year")
    
    for line in lines:
        # Check same line
        match = year_pattern.search(line.text)
        if match: return match.group(0)
        
        idx = graph.lines.index(line)
        if idx + 1 < len(graph.lines):
            match = year_pattern.search(graph.lines[idx+1].text)
            if match: return match.group(0)
            
    # Fallback search anywhere
    for w in graph.words:
        match = year_pattern.search(w.text)
        if match: return match.group(0)
        
    return None

def extract_board_university(graph: DocumentGraph) -> Optional[str]:
    # Usually at the top of the document (first few lines)
    rejects = ["STATEMENT", "MARKSHEET", "CERTIFICATE", "PASSING"]
    for i in range(min(10, len(graph.lines))):
        text = graph.lines[i].text.upper()
        if "BOARD" in text or "UNIVERSITY" in text or "COUNCIL" in text:
            if not any(r in text for r in rejects):
                return graph.lines[i].text.strip()
    return None
