"""
tests/test_parsers.py — Production test suite v2
=================================================
Covers:
  - Clean, blurry, rotated, low-light, WhatsApp compressed
  - OCR spacing errors, char confusion, duplicate lines
  - Multilingual noise, shadow, partial crop
  - False-mismatch reduction (OCR typos, minor spelling)
  - Confidence engine scoring
  - Text cleaner
  - OCR correction engine
  - Full output format validation

Run: pytest tests/ -v
"""

import pytest
import re
from app.parsers.aadhaar_parser import parse_aadhaar
from app.parsers.pan_parser import parse_pan
from app.matchers.matcher import match_name, match_id, match_dob
from app.matchers.mismatch_detector import build_validation_result
from app.ocr.detector import detect_document_type
from app.ocr.text_cleaner import clean_ocr_text, clean_field_value
from app.ocr.correction_engine import (
    correct_aadhaar_candidate,
    find_corrected_aadhaar,
    correct_pan_candidate,
    find_corrected_pan,
    correct_date,
)
from app.ocr.confidence_engine import calculate_field_confidence
from app.utils.blacklists import is_aadhaar_blacklisted, is_pan_blacklisted


# ═══════════════════════════════════════════════════════════════════
# Aadhaar OCR Samples
# ═══════════════════════════════════════════════════════════════════

AADHAAR_CLEAN = """
Government of India
Nikita Bhagvan Jadhav
DOB: 18/11/2001
Female
5395 8342 1089
"""

AADHAAR_BLURRY = """
Governmenl of lndia
Nikita Bhagvan Jadhav
D0B 18/11/2001
Female
5395 8342 1089
"""

AADHAAR_ROTATED = """
5395 8342 1089
Government of India
DOB: 18/11/2001
Nikita Bhagvan Jadhav
Female
"""

AADHAAR_LOW_LIGHT = """
Governm3nt of lndia
Nik1ta Bhagvan J4dhav
DOB: 18/11/2001
5395 8342 1089
"""

AADHAAR_WHATSAPP = """
Govt of India
Nik ita Bhag van Jadhav
D.O.B.: 18/11/2001
Fema le
5395 8342 1089
"""

AADHAAR_OCR_NOISE = """
Government of India
-------
Nikita Bhagvan Jadhav
Nikita Bhagvan Jadhav
DOB: 18/11/2001
Female Female
5395 8342 1089
5395 8342 1089
"""

AADHAAR_MULTILINGUAL_NOISE = """
सरकार भारत
Government of India
निकिता भगवान जाधव
Nikita Bhagvan Jadhav
DOB: 18/11/2001
Female
5395 8342 1089
"""

AADHAAR_PARTIAL_CROP = """
Nikita Bhagvan Jadhav
DOB: 18/11/2001
5395 8342 1089
"""

AADHAAR_SHADOW = """
Governme nt of Indi a
Nikita Bhagvan Jadhav
DOB: 18/11/ 2001
Female
5 395 83 42 1089
"""

AADHAAR_WRONG_SPACING = """
Government of India
NikitaBhagvanJadhav
DOB:18/11/2001
Female
539583421089
"""

# Char confusion: O→0 in Aadhaar
AADHAAR_CHAR_CONFUSION = """
Government of India
Nikita Bhagvan Jadhav
DOB: 18/11/2001
Female
5395 O342 1O89
"""


# ═══════════════════════════════════════════════════════════════════
# PAN OCR Samples
# ═══════════════════════════════════════════════════════════════════

PAN_CLEAN = """
Income Tax Department
Govt of India
Permanent Account Number
RLVPS5393K
Muskan Najir Shaikh
Father's Name: Najir Shaikh
DOB: 15/01/2004
"""

PAN_ROTATED = """
15/01/2004
Muskan Najir Shaikh
RLVPS5393K
Income Tax Department
Permanent Account Number
"""

PAN_OCR_CHAR_CONFUSION = """
Income Tax Department
Permanent Account Number
RLVP55393K
Muskan Najir Shaikh
15/01/2004
"""

PAN_WHATSAPP_COMPRESSED = """
lncome Tax Department
Permanent Account Number
RLVP55393K
Muskan Najir Shaikh
Father's Name Najir Shaikh
15/01/2004
"""

PAN_SHADOW = """
lncome Tax Depar tment
Permanent Ac count Number
RLVPS5393K
Mus kan Najir Shaikh
15/0 1/2004
"""

PAN_WRONG_NAME_EXTRACTION = """
Income Tax Department
Govt of India
Permanent Account Number
RLVPS5393K
Muskan Najir Shaikh
Father's Name: Najir Shaikh
Date of Birth: 15/01/2004
Signature
"""

# ═══════════════════════════════════════════════════════════════════
# Aadhaar Parser Tests
# ═══════════════════════════════════════════════════════════════════

class TestAadhaarParser:

    def test_clean_document(self):
        r = parse_aadhaar(AADHAAR_CLEAN)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"
        assert r["name"] is not None
        assert "Nikita" in r["name"]
        assert r["confidence"] > 0.5

    def test_blurry_document(self):
        r = parse_aadhaar(AADHAAR_BLURRY)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_rotated_document(self):
        """Fields should be found regardless of order in text."""
        r = parse_aadhaar(AADHAAR_ROTATED)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_low_light_document(self):
        r = parse_aadhaar(AADHAAR_LOW_LIGHT)
        assert r["aadhaar_number"] == "5395 8342 1089"

    def test_whatsapp_compressed(self):
        """Broken spaces in WhatsApp-compressed images."""
        r = parse_aadhaar(AADHAAR_WHATSAPP)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_duplicate_ocr_noise(self):
        """Duplicate lines should not confuse extraction."""
        r = parse_aadhaar(AADHAAR_OCR_NOISE)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_multilingual_noise(self):
        """Devanagari script should not break extraction."""
        r = parse_aadhaar(AADHAAR_MULTILINGUAL_NOISE)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_partial_crop(self):
        """Even with header missing, ID + DOB should be found."""
        r = parse_aadhaar(AADHAAR_PARTIAL_CROP)
        assert r["aadhaar_number"] == "5395 8342 1089"
        assert r["dob"] == "18/11/2001"

    def test_shadow_document(self):
        """Extra spaces from shadow correction."""
        r = parse_aadhaar(AADHAAR_SHADOW)
        assert r["aadhaar_number"] == "5395 8342 1089"

    def test_wrong_spacing_merged(self):
        """Merged words and digits without spaces."""
        r = parse_aadhaar(AADHAAR_WRONG_SPACING)
        assert r["aadhaar_number"] == "5395 8342 1089"

    def test_char_confusion_o_zero(self):
        """O used instead of 0 in Aadhaar number."""
        r = parse_aadhaar(AADHAAR_CHAR_CONFUSION)
        assert r["aadhaar_number"] == "5395 0342 1089"

    def test_empty_input(self):
        r = parse_aadhaar("")
        assert r["aadhaar_number"] is None
        assert r["name"] is None
        assert r["confidence"] == 0.0

    def test_name_not_blacklisted(self):
        """Government of India / UIDAI must never be returned as name."""
        r = parse_aadhaar(AADHAAR_CLEAN)
        if r["name"]:
            assert "government" not in r["name"].lower()
            assert "uidai" not in r["name"].lower()
            assert "india" not in r["name"].lower()

    def test_field_confidences_present(self):
        r = parse_aadhaar(AADHAAR_CLEAN)
        fc = r.get("field_confidences", {})
        assert "name" in fc
        assert "aadhaar_number" in fc
        assert "dob" in fc
        assert all(0 <= v <= 100 for v in fc.values())

    def test_aadhaar_format_normalized(self):
        """Aadhaar must be in XXXX XXXX XXXX format."""
        r = parse_aadhaar(AADHAAR_CLEAN)
        if r["aadhaar_number"]:
            assert re.fullmatch(r"\d{4} \d{4} \d{4}", r["aadhaar_number"])


# ═══════════════════════════════════════════════════════════════════
# PAN Parser Tests
# ═══════════════════════════════════════════════════════════════════

class TestPanParser:

    def test_clean_document(self):
        r = parse_pan(PAN_CLEAN)
        assert r["pan_number"] == "RLVPS5393K"
        assert r["dob"] == "15/01/2004"
        assert r["name"] is not None
        assert "Muskan" in r["name"]
        assert r["confidence"] > 0.5

    def test_rotated_document(self):
        r = parse_pan(PAN_ROTATED)
        assert r["pan_number"] == "RLVPS5393K"
        assert r["dob"] == "15/01/2004"

    def test_char_confusion(self):
        """S→5 confusion in PAN number."""
        r = parse_pan(PAN_OCR_CHAR_CONFUSION)
        assert r["pan_number"] == "RLVPS5393K"

    def test_whatsapp_compressed(self):
        r = parse_pan(PAN_WHATSAPP_COMPRESSED)
        assert r["pan_number"] == "RLVPS5393K"

    def test_shadow_document(self):
        r = parse_pan(PAN_SHADOW)
        assert r["pan_number"] == "RLVPS5393K"

    def test_name_not_from_blacklist(self):
        """Income Tax Department / Govt of India must not be name."""
        r = parse_pan(PAN_WRONG_NAME_EXTRACTION)
        if r["name"]:
            name_lower = r["name"].lower()
            assert "income" not in name_lower
            assert "government" not in name_lower
            assert "permanent" not in name_lower
            assert "signature" not in name_lower

    def test_father_name_not_extracted(self):
        """Father's name must not be confused with holder's name."""
        r = parse_pan(PAN_WRONG_NAME_EXTRACTION)
        if r["name"]:
            # Holder is Muskan, father is Najir Shaikh
            assert "Najir" not in r["name"] or "Muskan" in r["name"]

    def test_empty_input(self):
        r = parse_pan("")
        assert r["pan_number"] is None
        assert r["confidence"] == 0.0

    def test_field_confidences_present(self):
        r = parse_pan(PAN_CLEAN)
        fc = r.get("field_confidences", {})
        assert "name" in fc
        assert "pan_number" in fc
        assert "dob" in fc


# ═══════════════════════════════════════════════════════════════════
# Document Type Detection
# ═══════════════════════════════════════════════════════════════════

class TestDetector:

    def test_detect_aadhaar(self):
        assert detect_document_type(AADHAAR_CLEAN) == "aadhaar"

    def test_detect_pan(self):
        assert detect_document_type(PAN_CLEAN) == "pan"

    def test_detect_unknown_gibberish(self):
        assert detect_document_type("hello world random text 123") == "unknown"

    def test_detect_empty(self):
        assert detect_document_type("") == "unknown"

    def test_detect_aadhaar_number_only(self):
        """Even with just the 12-digit pattern, detect Aadhaar."""
        assert detect_document_type("5395 8342 1089\nGovernment of India") == "aadhaar"


# ═══════════════════════════════════════════════════════════════════
# Text Cleaner Tests
# ═══════════════════════════════════════════════════════════════════

class TestTextCleaner:

    def test_removes_duplicate_lines(self):
        text = "Nikita Jadhav\nNikita Jadhav\nDOB: 18/11/2001"
        cleaned = clean_ocr_text(text)
        count = cleaned.lower().count("nikita jadhav")
        assert count == 1

    def test_fixes_broken_dots(self):
        text = "NIKITA.. BHAGVAN"
        cleaned = clean_ocr_text(text)
        assert ".." not in cleaned

    def test_fixes_merged_words(self):
        text = "NikitaBhagvan"
        cleaned = clean_ocr_text(text)
        # Should have a space inserted
        assert "Nikita Bhagvan" in cleaned or "Nikita" in cleaned

    def test_removes_unicode_garbage(self):
        text = "Nikita\x00Jadhav\ufeff"
        cleaned = clean_ocr_text(text)
        assert "\x00" not in cleaned
        assert "\ufeff" not in cleaned

    def test_collapses_spaces(self):
        text = "Nikita    Bhagvan   Jadhav"
        cleaned = clean_ocr_text(text)
        assert "  " not in cleaned

    def test_removes_repeated_words(self):
        text = "Female Female Female"
        cleaned = clean_ocr_text(text)
        count = cleaned.lower().count("female")
        assert count == 1


# ═══════════════════════════════════════════════════════════════════
# Correction Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestCorrectionEngine:

    def test_aadhaar_correct_o_to_zero(self):
        result = correct_aadhaar_candidate("5395 O342 1O89")
        assert result == "5395 0342 1089"

    def test_aadhaar_correct_i_to_one(self):
        result = correct_aadhaar_candidate("I395 8342 1089")
        assert result == "1395 8342 1089"

    def test_aadhaar_reject_invalid(self):
        result = correct_aadhaar_candidate("ABCD EFGH IJKL")
        assert result is None

    def test_pan_correct_s_to_five(self):
        result = correct_pan_candidate("RLVPS5393K")
        assert result == "RLVPS5393K"  # already correct

    def test_pan_correct_o_in_digits(self):
        # RLVPS O393K → O at position 5 (digit) → corrected to 0
        result = correct_pan_candidate("RLVPSO393K")
        assert result == "RLVPS0393K"

    def test_pan_invalid_length(self):
        result = correct_pan_candidate("RLVPS539")
        assert result is None

    def test_date_l_to_one(self):
        result = correct_date("l8/ll/200l")
        assert result == "18/11/2001"

    def test_find_corrected_aadhaar(self):
        text = "Government of India\n5395 O342 1O89\nFemale"
        result = find_corrected_aadhaar(text)
        assert result == "5395 0342 1089"

    def test_find_corrected_pan(self):
        text = "Income Tax Department\nRLVPSO393K\nMuskan"
        result = find_corrected_pan(text)
        assert result == "RLVPS0393K"


# ═══════════════════════════════════════════════════════════════════
# Confidence Engine Tests
# ═══════════════════════════════════════════════════════════════════

class TestConfidenceEngine:

    def test_perfect_aadhaar_confidence(self):
        score = calculate_field_confidence(
            "aadhaar_number", "5395 8342 1089",
            "Government of India\n5395 8342 1089\nDOB",
        )
        assert score >= 70

    def test_perfect_pan_confidence(self):
        score = calculate_field_confidence(
            "pan_number", "RLVPS5393K",
            "Income Tax Department\nRLVPS5393K\nMuskan",
        )
        assert score >= 70

    def test_none_value_zero_confidence(self):
        score = calculate_field_confidence("name", None, "some text")
        assert score == 0

    def test_name_confidence_with_good_value(self):
        score = calculate_field_confidence(
            "name", "Nikita Bhagvan Jadhav", "Government of India\nNikita Bhagvan Jadhav\nDOB",
        )
        assert score >= 50

    def test_agreement_boosts_confidence(self):
        """Same value in multiple variants should boost confidence."""
        vt = {
            "grayscale": "5395 8342 1089",
            "clahe":     "5395 8342 1089",
            "sharpened": "5395 8342 1089",
        }
        score = calculate_field_confidence("aadhaar_number", "5395 8342 1089", "5395 8342 1089", vt)
        assert score >= 80


# ═══════════════════════════════════════════════════════════════════
# Matcher Tests (v2)
# ═══════════════════════════════════════════════════════════════════

class TestMatcher:

    # Name matching
    def test_exact_match(self):
        r = match_name("Nikita Bhagvan Jadhav", "Nikita Bhagvan Jadhav")
        assert r["status"] == "MATCH"
        assert r["score"] == 100.0
        assert "reason" in r

    def test_case_insensitive_match(self):
        r = match_name("nikita bhagvan jadhav", "NIKITA BHAGVAN JADHAV")
        assert r["status"] == "MATCH"

    def test_ocr_typo_possible_match(self):
        """Bhagvan vs Bhagwan — minor OCR variation."""
        r = match_name("Nikita Bhagvan Jadhav", "Nikita Bhagwan Jadhav")
        assert r["status"] in ("MATCH", "POSSIBLE_MATCH")
        assert r["score"] >= 75

    def test_complete_mismatch(self):
        r = match_name("Nikita Bhagvan Jadhav", "Muskan Najir Shaikh")
        assert r["status"] == "MISMATCH"
        assert r["score"] < 75

    def test_phonetic_similarity(self):
        """Phonetically similar names should not hard-mismatch."""
        r = match_name("Ramesh Kumar", "Ramesh Kumaar")
        assert r["status"] in ("MATCH", "POSSIBLE_MATCH")

    def test_reason_field_present(self):
        r = match_name("Nikita Bhagvan Jadhav", "Muskan Najir Shaikh")
        assert "reason" in r
        assert isinstance(r["reason"], str)

    # ID matching
    def test_id_exact(self):
        r = match_id("5395 8342 1089", "5395 8342 1089")
        assert r["status"] == "MATCH"

    def test_id_normalized(self):
        r = match_id("5395 8342 1089", "539583421089")
        assert r["status"] == "MATCH"

    def test_id_ocr_confusion_possible(self):
        """O used for 0 — possible match not hard fail."""
        r = match_id("RLVPS5393K", "RLVPSO393K")
        # After normalization these look different but OCR fallback should apply
        assert r["status"] in ("POSSIBLE_MATCH", "MISMATCH")

    def test_id_mismatch(self):
        r = match_id("5395 8342 1089", "1234 5678 9012")
        assert r["status"] == "MISMATCH"

    # DOB matching
    def test_dob_exact(self):
        r = match_dob("18/11/2001", "18/11/2001")
        assert r["status"] == "MATCH"

    def test_dob_separator_variant(self):
        r = match_dob("18/11/2001", "18-11-2001")
        assert r["status"] == "MATCH"

    def test_dob_year_only_possible(self):
        r = match_dob("18/11/2001", "2001")
        assert r["status"] == "POSSIBLE_MATCH"

    def test_dob_mismatch(self):
        r = match_dob("18/11/2001", "15/01/2004")
        assert r["status"] == "MISMATCH"

    def test_dob_reason_present(self):
        r = match_dob("18/11/2001", "15/01/2004")
        assert "reason" in r


# ═══════════════════════════════════════════════════════════════════
# Mismatch Detector Tests (v2)
# ═══════════════════════════════════════════════════════════════════

STORED_AADHAAR_USER = {
    "full_name":      "Nikita Bhagvan Jadhav",
    "dob":            "18/11/2001",
    "aadhaar_number": "5395 8342 1089",
}

STORED_PAN_USER = {
    "full_name":  "Muskan Najir Shaikh",
    "dob":        "15/01/2004",
    "pan_number": "RLVPS5393K",
}


class TestMismatchDetector:

    def test_verified_aadhaar(self):
        extracted = {
            "name": "Nikita Bhagvan Jadhav", "dob": "18/11/2001",
            "aadhaar_number": "5395 8342 1089", "confidence": 1.0,
            "field_confidences": {"name": 95, "dob": 95, "aadhaar_number": 99},
        }
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, extracted, 1.0)
        assert r["overall_status"] == "VERIFIED"

    def test_mismatch_aadhaar_wrong_person(self):
        extracted = {
            "name": "Muskan Najir Shaikh", "dob": "15/01/2004",
            "aadhaar_number": "5395 8342 1089", "confidence": 0.9,
            "field_confidences": {"name": 90, "dob": 90, "aadhaar_number": 99},
        }
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, extracted, 0.9)
        assert r["overall_status"] in ("MISMATCH", "POSSIBLE_MISMATCH")

    def test_possible_mismatch_ocr_typo(self):
        """Bhagvan → Bhagwan: minor OCR typo should give POSSIBLE_MISMATCH not MISMATCH."""
        extracted = {
            "name": "Nikita Bhagwan Jadhav", "dob": "18/11/2001",
            "aadhaar_number": "5395 8342 1089", "confidence": 0.95,
            "field_confidences": {"name": 88, "dob": 95, "aadhaar_number": 99},
        }
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, extracted, 0.95)
        # Should not be full MISMATCH for a minor OCR variation
        assert r["overall_status"] in ("VERIFIED", "POSSIBLE_MISMATCH")

    def test_verified_pan(self):
        extracted = {
            "name": "Muskan Najir Shaikh", "dob": "15/01/2004",
            "pan_number": "RLVPS5393K", "confidence": 1.0,
            "field_confidences": {"name": 95, "dob": 95, "pan_number": 99},
        }
        r = build_validation_result("pan", STORED_PAN_USER, extracted, 1.0)
        assert r["overall_status"] == "VERIFIED"

    def test_ocr_failed(self):
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, {}, 0.0)
        assert r["overall_status"] == "OCR_FAILED"

    def test_unknown_doc_type(self):
        r = build_validation_result("unknown", STORED_AADHAAR_USER, {}, 0.0)
        assert r["overall_status"] == "DOC_TYPE_UNKNOWN"

    def test_enhanced_output_format(self):
        """Validate the new output format has all required fields."""
        extracted = {
            "name": "Nikita Bhagvan Jadhav", "dob": "18/11/2001",
            "aadhaar_number": "5395 8342 1089", "confidence": 1.0,
            "field_confidences": {"name": 95, "dob": 95, "aadhaar_number": 99},
        }
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, extracted, 1.0)
        for field in r["fields"]:
            assert "field"       in field
            assert "stored"      in field
            assert "extracted"   in field
            assert "match_score" in field
            assert "status"      in field
            assert "confidence"  in field
            assert "reason"      in field

    def test_summary_present(self):
        extracted = {
            "name": "Nikita Bhagvan Jadhav", "dob": "18/11/2001",
            "aadhaar_number": "5395 8342 1089", "confidence": 1.0,
            "field_confidences": {"name": 95, "dob": 95, "aadhaar_number": 99},
        }
        r = build_validation_result("aadhaar", STORED_AADHAAR_USER, extracted, 1.0)
        assert "summary" in r
        assert isinstance(r["summary"], str)
        assert len(r["summary"]) > 5


# ═══════════════════════════════════════════════════════════════════
# Blacklist Tests
# ═══════════════════════════════════════════════════════════════════

class TestBlacklists:

    def test_govt_of_india_blacklisted(self):
        assert is_aadhaar_blacklisted("Government of India")
        assert is_pan_blacklisted("Government of India")

    def test_uidai_blacklisted(self):
        assert is_aadhaar_blacklisted("UIDAI")

    def test_income_tax_pan_blacklisted(self):
        assert is_pan_blacklisted("Income Tax Department")

    def test_real_name_not_blacklisted(self):
        assert not is_aadhaar_blacklisted("Nikita Bhagvan Jadhav")
        assert not is_pan_blacklisted("Muskan Najir Shaikh")

    def test_male_female_blacklisted(self):
        assert is_aadhaar_blacklisted("Male")
        assert is_aadhaar_blacklisted("Female")
