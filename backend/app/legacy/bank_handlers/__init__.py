"""
app/extraction/bank_handlers/__init__.py
Universal bank-handler registry.
Import the router here so callers can do:
    from app.extraction.bank_handlers import get_handler
"""
from app.extraction.bank_handlers.detector import detect_bank
from app.extraction.bank_handlers.generic_handler import GenericHandler
from app.extraction.bank_handlers.sbi_handler import SBIHandler
from app.extraction.bank_handlers.kotak_handler import KotakHandler

_REGISTRY = {
    "SBI":   SBIHandler,
    "KOTAK": KotakHandler,
}

def get_handler(bank_tag: str):
    """Return the appropriate handler instance for the detected bank."""
    cls = _REGISTRY.get(bank_tag, GenericHandler)
    return cls()
