"""
app/extraction/extraction_profiles.py
=======================================
Extraction Profiles — controlled OCR routing.

Each profile bundles OCR settings, preprocessing, table mode, language lock,
and semantic toggles into a single named configuration.

Philosophy:
    One universal pipeline cannot solve all document types.
    Profiles give users + the system controlled routing
    WITHOUT rebuilding the architecture.

Usage:
    profile = get_profile("marathi_document")
    # profile.lang = "mar"
    # profile.table_reconstruction = False
    # profile.safe_mode = True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ExtractionProfile:
    """
    Complete OCR extraction configuration for a document type.
    All fields have safe defaults.
    """
    name: str                           # profile key (internal)
    label: str                          # display name in UI

    # ── Language Routing ───────────────────────────────────────────────────────
    lang: str = "auto"                  # Tesseract lang string or "auto"
    lang_fallback: List[str] = field(default_factory=lambda: ["eng"])
    force_lang: bool = False            # True = skip auto-detection entirely

    # ── OCR Engine ────────────────────────────────────────────────────────────
    ocr_engine: str = "auto"            # "paddle" | "tesseract" | "auto"
    oem: int = 3                        # Tesseract OEM (1=LSTM only, 3=Legacy+LSTM)
    psm: int = 11                       # Tesseract PSM (6=block, 11=sparse, 7=line)

    # ── Preprocessing ─────────────────────────────────────────────────────────
    aggressive_denoise: bool = False    # Heavy denoising for old/dirty scans
    binarize: bool = False              # Force binarization (old ink, faded text)
    deskew: bool = True                 # Deskew correction
    upscale_small: bool = True          # Upscale small crops for better OCR

    # ── Document Mode ─────────────────────────────────────────────────────────
    handwritten_mode: bool = False      # Force LSTM-only, no PaddleOCR
    financial_mode: bool = False        # Strict column alignment for numbers

    # ── Table Engine ──────────────────────────────────────────────────────────
    table_reconstruction: bool = True   # True = try to detect/reconstruct tables
    table_confidence_threshold: float = 0.35  # Min confidence to attempt table
    geometry_table_only: bool = False   # True = only geometry lines, no cluster fallback

    # ── Semantic / Intelligence Layers ────────────────────────────────────────
    safe_mode: bool = False             # True = disable ALL intelligence layers
    semantic_reconstruction: bool = True  # False = raw blocks only
    semantic_understanding: bool = True   # False = skip entity extraction
    active_learning: bool = True          # False = skip correction hints
    memory_store: bool = True            # False = skip signature persistence
    digital_twin: bool = True            # False = skip twin generation

    # ── Output ────────────────────────────────────────────────────────────────
    preserve_raw_ocr: bool = True       # Always True now (Phase 6.5)
    confidence_threshold: float = 0.20  # Min block confidence to show

    # ── Description ───────────────────────────────────────────────────────────
    description: str = ""
    icon: str = "📄"


# ── Profile Definitions ───────────────────────────────────────────────────────

PROFILES: Dict[str, ExtractionProfile] = {

    "auto": ExtractionProfile(
        name="auto",
        label="Auto",
        icon="🤖",
        lang="auto",
        description="Automatic detection. Best for clean, printed documents.",
    ),

    "clean_pdf": ExtractionProfile(
        name="clean_pdf",
        label="Clean PDF",
        icon="📃",
        lang="auto",
        ocr_engine="paddle",
        oem=3,
        psm=6,
        table_reconstruction=True,
        table_confidence_threshold=0.50,
        description="High-quality digital PDFs. Maximum confidence thresholds.",
    ),

    "bank_statement": ExtractionProfile(
        name="bank_statement",
        label="Bank Statement",
        icon="🏦",
        lang="eng",
        force_lang=True,
        ocr_engine="auto",
        oem=3,
        psm=6,
        financial_mode=True,
        table_reconstruction=True,
        table_confidence_threshold=0.45,
        geometry_table_only=True,    # Only grid-line tables — no clustering guesses
        safe_mode=False,
        semantic_reconstruction=False,  # Don't merge lines into fake paragraphs
        description="Bank statements, financial reports. English only, strict column alignment.",
    ),

    "old_scan": ExtractionProfile(
        name="old_scan",
        label="Old Scan",
        icon="📜",
        lang="auto",
        oem=1,                          # LSTM only (better for degraded text)
        psm=6,
        aggressive_denoise=True,
        binarize=True,
        table_confidence_threshold=0.50,  # Higher threshold — old scans hallucinate
        safe_mode=True,
        semantic_reconstruction=False,
        description="Old, yellowed, or degraded scans. Heavy preprocessing, no hallucination.",
    ),

    "handwritten": ExtractionProfile(
        name="handwritten",
        label="Handwritten",
        icon="✏️",
        lang="eng",
        force_lang=False,               # Will auto-detect per region
        oem=1,                          # LSTM only — required for handwriting
        psm=6,
        handwritten_mode=True,
        aggressive_denoise=True,
        table_reconstruction=False,     # Never reconstruct tables from handwriting
        safe_mode=True,
        semantic_reconstruction=False,
        digital_twin=False,
        confidence_threshold=0.10,      # Keep even low-confidence handwriting
        description="Handwritten documents. LSTM-only OCR, no table reconstruction.",
    ),

    "marathi_document": ExtractionProfile(
        name="marathi_document",
        label="Marathi Document",
        icon="🇮🇳",
        lang="mar",
        force_lang=True,                # Lock to Marathi — never use mar+hin+eng
        ocr_engine="tesseract",         # PaddleOCR has poor Devanagari support
        oem=1,                          # LSTM only — required for Devanagari accuracy
        psm=6,
        handwritten_mode=False,         # Use profile-level override instead
        aggressive_denoise=True,
        table_reconstruction=False,     # Ration cards rarely have clean grid tables
        table_confidence_threshold=0.50,
        safe_mode=True,
        semantic_reconstruction=False,
        active_learning=False,
        confidence_threshold=0.10,      # Never discard Devanagari
        description="Marathi-language documents: ration cards, certificates, government forms. Pure Marathi OCR.",
    ),

    "hindi_document": ExtractionProfile(
        name="hindi_document",
        label="Hindi Document",
        icon="🇮🇳",
        lang="hin",
        force_lang=True,
        ocr_engine="tesseract",
        oem=1,
        psm=6,
        aggressive_denoise=True,
        table_reconstruction=False,
        safe_mode=True,
        semantic_reconstruction=False,
        confidence_threshold=0.10,
        description="Hindi-language documents. Pure Hindi OCR with LSTM engine.",
    ),

    "government_form": ExtractionProfile(
        name="government_form",
        label="Government Form",
        icon="🏛️",
        lang="auto",
        oem=1,
        psm=6,
        aggressive_denoise=True,
        table_reconstruction=True,
        table_confidence_threshold=0.40,
        geometry_table_only=True,
        safe_mode=True,
        semantic_reconstruction=False,
        confidence_threshold=0.15,
        description="Government forms, certificates, official documents. Mixed language, form field extraction.",
    ),

    "table_heavy": ExtractionProfile(
        name="table_heavy",
        label="Table Heavy",
        icon="📊",
        lang="auto",
        ocr_engine="auto",
        oem=3,
        psm=6,
        financial_mode=True,
        table_reconstruction=True,
        table_confidence_threshold=0.30,
        geometry_table_only=True,
        safe_mode=False,
        semantic_reconstruction=False,
        description="Documents with many tables: invoices, reports, schedules. Geometry-first table detection.",
    ),

    "mixed_language": ExtractionProfile(
        name="mixed_language",
        label="Mixed Language",
        icon="🌐",
        lang="auto",
        force_lang=False,
        ocr_engine="auto",
        oem=1,
        psm=11,
        table_reconstruction=True,
        table_confidence_threshold=0.40,
        safe_mode=True,
        semantic_reconstruction=False,
        confidence_threshold=0.15,
        description="Documents with multiple languages (e.g., English + Marathi). Per-region language detection.",
    ),

    "low_quality_scan": ExtractionProfile(
        name="low_quality_scan",
        label="Low Quality Scan",
        icon="🔍",
        lang="auto",
        oem=1,
        psm=6,
        aggressive_denoise=True,
        binarize=True,
        upscale_small=True,
        table_confidence_threshold=0.60,  # Very strict — don't hallucinate on noise
        table_reconstruction=False,
        safe_mode=True,
        semantic_reconstruction=False,
        digital_twin=False,
        confidence_threshold=0.10,
        description="Very low quality, noisy, or compressed scans. Maximum preprocessing, minimum hallucination.",
    ),
}


def get_profile(name: str) -> ExtractionProfile:
    """Get extraction profile by name. Falls back to 'auto' if not found."""
    return PROFILES.get(name, PROFILES["auto"])


def get_profile_list() -> List[Dict]:
    """Return profile list for frontend dropdown."""
    return [
        {
            "name":        p.name,
            "label":       p.label,
            "icon":        p.icon,
            "description": p.description,
        }
        for p in PROFILES.values()
    ]


def apply_profile_to_pipeline(
    profile: ExtractionProfile,
    safe_mode_override: bool = False,
    handwritten_override: bool = False,
    lang_override: Optional[str] = None,
) -> Dict:
    """
    Resolve final pipeline configuration from profile + UI overrides.

    UI overrides always win over profile defaults.

    Returns a flat config dict used throughout the pipeline.
    """
    # Start with profile settings
    cfg = {
        "lang":                       profile.lang,
        "force_lang":                 profile.force_lang,
        "ocr_engine":                 profile.ocr_engine,
        "oem":                        profile.oem,
        "psm":                        profile.psm,
        "aggressive_denoise":         profile.aggressive_denoise,
        "binarize":                   profile.binarize,
        "deskew":                     profile.deskew,
        "upscale_small":              profile.upscale_small,
        "handwritten_mode":           profile.handwritten_mode,
        "financial_mode":             profile.financial_mode,
        "table_reconstruction":       profile.table_reconstruction,
        "table_confidence_threshold": profile.table_confidence_threshold,
        "geometry_table_only":        profile.geometry_table_only,
        "safe_mode":                  profile.safe_mode,
        "semantic_reconstruction":    profile.semantic_reconstruction,
        "semantic_understanding":     profile.semantic_understanding,
        "active_learning":            profile.active_learning,
        "memory_store":               profile.memory_store,
        "digital_twin":               profile.digital_twin,
        "preserve_raw_ocr":           profile.preserve_raw_ocr,
        "confidence_threshold":       profile.confidence_threshold,
    }

    # Apply UI overrides
    if safe_mode_override:
        cfg["safe_mode"]              = True
        cfg["semantic_reconstruction"] = False
        cfg["semantic_understanding"]  = False
        cfg["active_learning"]         = False
        cfg["memory_store"]            = False
        cfg["digital_twin"]            = False
        cfg["table_reconstruction"]    = cfg.get("table_reconstruction", True)
        # Keep table_reconstruction as-is (profile decides)

    if handwritten_override:
        cfg["handwritten_mode"] = True
        cfg["oem"]              = 1     # LSTM only
        cfg["psm"]              = 6
        cfg["table_reconstruction"] = False  # Never table from handwriting
        cfg["ocr_engine"]       = "tesseract"  # PaddleOCR has no handwriting support

    if lang_override and lang_override != "auto":
        cfg["lang"]       = lang_override
        cfg["force_lang"] = True

    # If safe_mode: always disable intelligence layers
    if cfg["safe_mode"]:
        cfg["semantic_reconstruction"] = False
        cfg["semantic_understanding"]  = False
        cfg["active_learning"]         = False
        cfg["memory_store"]            = False
        cfg["digital_twin"]            = False

    return cfg
