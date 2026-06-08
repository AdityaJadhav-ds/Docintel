import logging

logger = logging.getLogger(__name__)

REASONING_DB = {}

def track_reasoning(field: str, anchor_used: str, candidates: list, rejected: list, selected: str):
    """Stores the extraction reasoning for debug and auditing."""
    reasoning = {
        "anchor_used": anchor_used,
        "candidate_pool": candidates,
        "rejected": rejected,
        "selected": selected
    }
    REASONING_DB[field] = reasoning
    logger.debug(f"[Extraction Reasoner] {field}: selected='{selected}' from {len(candidates)} candidates.")

def get_reasoning() -> dict:
    return REASONING_DB

def clear_reasoning():
    REASONING_DB.clear()
