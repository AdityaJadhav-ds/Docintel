"""
tests/test_marksheet_extraction.py
=====================================
Simulates the OCR word output for all 5 real marksheets and verifies
that the semantic parser + validation pipeline extracts correct fields.

These tests run WITHOUT images — they inject realistic OCR word lists
that mimic what the OCR fusion engine would produce from each marksheet.

Ground truth:
  1. SSC 2000  — LANDAGE SUNIL MANOHAR, 71.33%, 535/750, PASS
  2. HSC 2022  — Jadhav Aditya Bhagvan, 75.17%, 451/600, PASS
  3. SSC 2020  — Jadhav Aditya Bhagvan, 82.40%, 412/500, DISTINCTION
  4. SSC 1988  — LOANA GIRISHKUMAR GHANASHAM, 37.28%, 261/700, PASS
  5. HSC 2022c — Jadhav Aditya Bhagvan, 75.17%, 451/600, DISTINCTION

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe -m pytest tests/test_marksheet_extraction.py -v
"""
import os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from app.academic_engine.semantic_engine.semantic_parser import SemanticParser
from app.academic_engine.validation_engine.healing_pipeline import HealingPipeline
from app.academic_engine.master_pipeline import MasterPipeline


def _w(text, x, y, w=80, h=20, conf=0.9):
    """Helper: create a word dict."""
    return {"text": text, "confidence": conf, "bbox": (x, y, w, h)}


def _run_pipeline(words):
    """Run semantic + validation and return valid_fields."""
    parser = SemanticParser()
    healer = HealingPipeline()
    mp = MasterPipeline.__new__(MasterPipeline)

    semantic = parser.parse(words)
    def _no_ocr(img, v): return {"text": "", "confidence": 0.0}
    healed_raw = healer.process(
        extracted_fields=semantic["fields"],
        full_document_text=" ".join(w["text"] for w in words),
        image_crops={},
        ocr_callable=_no_ocr,
    )
    valid, _ = mp._sanitize(healed_raw["healed_fields"])
    return valid


def _val(fields, key):
    f = fields.get(key, {})
    if isinstance(f, dict):
        return f.get("value")
    return f


# ─────────────────────────────────────────────────────────────────────
# MARKSHEET 1: SSC 2000 Kolhapur — LANDAGE SUNIL MANOHAR
# ─────────────────────────────────────────────────────────────────────
SSC_2000_WORDS = [
    _w("STATEMENT", 100, 10),
    _w("OF", 200, 10),
    _w("MARKS", 240, 10),
    _w("DIVISIONAL", 10, 40), _w("BOARD", 100, 40),
    _w("KOLHAPUR", 150, 60),
    _w("SEAT", 10, 80), _w("NO.", 60, 80), _w("F073951", 100, 80),
    _w("MARCH-2000", 300, 80),
    # Candidate name (label + value on same row / next row)
    _w("CANDIDATE'S", 10, 120), _w("FULL", 120, 120), _w("NAME", 170, 120),
    _w("LANDAGE", 10, 140, conf=0.92), _w("SUNIL", 90, 140, conf=0.93), _w("MANOHAR", 150, 140, conf=0.91),
    # Marks table
    _w("MAXIMUM", 10, 200), _w("MARKS", 100, 200),
    _w("100", 200, 200), _w("100", 280, 200), _w("100", 360, 200),
    _w("150", 440, 200), _w("150", 520, 200), _w("150", 600, 200),
    _w("750", 680, 200),
    _w("MARKS", 10, 240), _w("OBTAINED", 80, 240),
    _w("075", 200, 240), _w("070", 280, 240), _w("054", 360, 240),
    _w("098", 440, 240), _w("122", 520, 240), _w("116", 600, 240),
    _w("535", 680, 240),
    # Percentage & Result
    _w("PERCENTAGE", 620, 200),
    _w("71", 620, 240), _w("33", 660, 240, conf=0.89),
    _w("RESULT", 720, 200),
    _w("PASS", 720, 240),
]


class TestSSC2000:
    def test_name(self):
        fields = _run_pipeline(SSC_2000_WORDS)
        name = _val(fields, "name")
        assert name is not None, "Name not extracted"
        assert "LANDAGE" in str(name).upper() or "SUNIL" in str(name).upper(), \
            f"Wrong name: {name}"

    def test_percentage(self):
        fields = _run_pipeline(SSC_2000_WORDS)
        pct = _val(fields, "percentage")
        assert pct is not None, "Percentage not extracted"
        assert abs(float(pct) - 71.33) < 1.0, f"Wrong percentage: {pct}"

    def test_result(self):
        fields = _run_pipeline(SSC_2000_WORDS)
        result = _val(fields, "result")
        assert result == "PASS", f"Wrong result: {result}"

    def test_marks(self):
        fields = _run_pipeline(SSC_2000_WORDS)
        obt = _val(fields, "obtained_marks")
        tot = _val(fields, "total_marks")
        if obt is not None:
            assert abs(float(obt) - 535) < 2, f"Wrong obtained: {obt}"
        if tot is not None:
            assert abs(float(tot) - 750) < 2, f"Wrong total: {tot}"


# ─────────────────────────────────────────────────────────────────────
# MARKSHEET 2: HSC 2022 Statement — Jadhav Aditya Bhagvan
# THE KNOWN BUG: H225007404 must NOT be extracted as percentage
# ─────────────────────────────────────────────────────────────────────
HSC_2022_WORDS = [
    _w("HIGHER", 100, 10), _w("SECONDARY", 200, 10),
    _w("CERTIFICATE", 320, 10), _w("EXAMINATION", 450, 10),
    _w("SCIENCE", 10, 40),
    _w("SEAT", 10, 60), _w("NO.", 60, 60), _w("X006102", 100, 60),
    _w("MARCH-22", 300, 60),
    # Candidate name
    _w("CANDIDATE'S", 10, 100), _w("FULL", 120, 100), _w("NAME", 170, 100),
    _w("Jadhav", 10, 130, conf=0.95), _w("Aditya", 90, 130, conf=0.96), _w("Bhagvan", 160, 130, conf=0.93),
    # Mother name (should NOT be extracted as candidate name)
    _w("CANDIDATE'S", 10, 160), _w("MOTHER'S", 120, 160), _w("NAME", 200, 160),
    _w("Nita", 10, 180, conf=0.90),
    # Subject marks
    _w("01", 10, 220), _w("ENGLISH", 50, 220), _w("ENG", 200, 220), _w("100", 280, 220), _w("063", 360, 220),
    _w("54", 10, 250), _w("PHYSICS", 50, 250), _w("ENG", 200, 250), _w("100", 280, 250), _w("071", 360, 250),
    # Total marks row
    _w("टकेवारी/", 10, 380), _w("Percentage", 100, 380),
    _w("75.17", 250, 380, conf=0.97),
    _w("एकूण", 350, 380), _w("गुण/Total", 430, 380), _w("Marks", 530, 380),
    _w("600", 620, 380, conf=0.95), _w("451", 700, 380, conf=0.96),
    # Result
    _w("Result/", 10, 420), _w("निकाल", 100, 420),
    _w("PASS", 250, 420, conf=0.97),
    # CRITICAL: Barcode/serial that must NOT be extracted as percentage
    _w("H225007404", 200, 500, conf=0.75),
    _w("3713399945898", 10, 530, conf=0.70),
]


class TestHSC2022Statement:
    def test_name(self):
        fields = _run_pipeline(HSC_2022_WORDS)
        name = _val(fields, "name")
        assert name is not None, "Name not extracted"
        n = str(name).lower()
        assert "jadhav" in n or "aditya" in n, f"Wrong name: {name}"

    def test_percentage_correct(self):
        """Must extract 75.17, NOT H225007404 or 3713399945898."""
        fields = _run_pipeline(HSC_2022_WORDS)
        pct = _val(fields, "percentage")
        assert pct is not None, "Percentage not extracted at all"
        assert abs(float(pct) - 75.17) < 0.5, f"Wrong percentage: {pct} (expected 75.17)"

    def test_barcode_rejected(self):
        """H225007404 must be rejected as hallucination."""
        from app.academic_engine.validation_engine.hallucination_detector import HallucinationDetector
        hd = HallucinationDetector()
        is_hal, msg = hd.is_hallucination("percentage", "H225007404", 0.75)
        assert is_hal, f"Barcode H225007404 should be hallucination but wasn't: {msg}"

    def test_result(self):
        fields = _run_pipeline(HSC_2022_WORDS)
        result = _val(fields, "result")
        assert result == "PASS", f"Wrong result: {result}"

    def test_total_marks(self):
        fields = _run_pipeline(HSC_2022_WORDS)
        tot = _val(fields, "total_marks")
        obt = _val(fields, "obtained_marks")
        if tot is not None:
            assert abs(float(tot) - 600) < 2, f"Wrong total: {tot}"
        if obt is not None:
            assert abs(float(obt) - 451) < 2, f"Wrong obtained: {obt}"


# ─────────────────────────────────────────────────────────────────────
# MARKSHEET 3: SSC 2020 Certificate — Jadhav Aditya Bhagvan, 82.40%
# Has grace marks: 407+05 = 412
# ─────────────────────────────────────────────────────────────────────
SSC_2020_WORDS = [
    _w("SECONDARY", 100, 10), _w("SCHOOL", 210, 10), _w("CERTIFICATE", 290, 10),
    _w("EXAMINATION", 420, 10), _w("CERTIFICATE", 550, 10),
    _w("This", 10, 60), _w("is", 50, 60), _w("to", 70, 60), _w("certify", 90, 60), _w("that", 150, 60),
    _w("Jadhav", 10, 90, conf=0.96), _w("Aditya", 90, 90, conf=0.95), _w("Bhagvan", 160, 90, conf=0.94),
    _w("Mother", 10, 115), _w("Name", 80, 115),
    _w("Nita", 200, 115, conf=0.90),
    _w("DIVISIONAL", 10, 140), _w("BOARD", 100, 140),
    _w("KOLHAPUR", 10, 165),
    _w("SEAT", 10, 190), _w("NO.", 60, 190), _w("F010664", 100, 190),
    # Subject marks
    _w("MARATHI", 10, 240), _w("(1ST", 120, 240), _w("LANG)", 160, 240),
    _w("100", 280, 240), _w("089", 360, 240),
    _w("HINDI", 10, 270), _w("(2/3", 80, 270), _w("LANG)", 125, 270),
    _w("100", 280, 270), _w("066", 360, 270),
    _w("ENGLISH", 10, 300), _w("(2/3", 90, 300), _w("LANG)", 135, 300),
    _w("100", 280, 300), _w("080", 360, 300),
    _w("MATHEMATICS", 10, 330),
    _w("100", 280, 330), _w("071", 360, 330),
    _w("SCIENCE", 10, 360), _w("&", 90, 360), _w("TECHNOLOGY", 110, 360),
    _w("100", 280, 360), _w("085", 360, 360),
    _w("SOCIAL", 10, 390), _w("SCIENCES", 80, 390),
    _w("100", 280, 390), _w("082", 360, 390),
    # Totals — SSC 2020 shows "500 £407+05"
    _w("एकूण", 10, 430), _w("गुण/Total", 80, 430), _w("Marks", 180, 430),
    _w("500", 280, 430, conf=0.96), _w("£407+05", 370, 430, conf=0.85),
    # Percentage
    _w("PERCENTAGE", 10, 470), _w("£", 160, 470), _w("82.40", 180, 470, conf=0.95),
    # Result
    _w("DISTINCTION", 10, 510, conf=0.93),
    # QR serial (must be rejected)
    _w("CS205008392", 300, 600, conf=0.72),
]


class TestSSC2020:
    def test_name(self):
        fields = _run_pipeline(SSC_2020_WORDS)
        name = _val(fields, "name")
        assert name is not None, "Name not extracted"
        assert "jadhav" in str(name).lower() or "aditya" in str(name).lower(), \
            f"Wrong name: {name}"

    def test_percentage(self):
        fields = _run_pipeline(SSC_2020_WORDS)
        pct = _val(fields, "percentage")
        assert pct is not None, "Percentage not extracted"
        assert abs(float(pct) - 82.40) < 1.0, f"Wrong percentage: {pct}"

    def test_result_distinction(self):
        fields = _run_pipeline(SSC_2020_WORDS)
        result = _val(fields, "result")
        assert result == "DISTINCTION", f"Wrong result: {result}"

    def test_grace_marks_repair(self):
        """407+05 should be repaired to 412."""
        from app.academic_engine.validation_engine.numeric_repair import NumericRepair
        nr = NumericRepair()
        val, repaired = nr.repair("407+05", "obtained_marks")
        assert val == "412", f"Grace marks not repaired correctly: {val}"
        assert repaired is True


# ─────────────────────────────────────────────────────────────────────
# MARKSHEET 4: SSC 1988 Pune — LOANA GIRISHKUMAR GHANASHAM, 37.28%
# ─────────────────────────────────────────────────────────────────────
SSC_1988_WORDS = [
    _w("Maharashtra", 100, 10), _w("State", 210, 10), _w("Board", 270, 10),
    _w("PUNE-411010", 10, 40),
    _w("DIVISIONAL", 10, 60), _w("BOARD", 100, 60),
    _w("PUNE", 150, 80),
    _w("EXAM.", 200, 80), _w("SEAT", 280, 80), _w("NO.", 330, 80),
    _w("F261829", 370, 80),
    _w("MARCH-1988", 500, 80),
    # Candidate name
    _w("CANDIDATE'S", 10, 120), _w("FULL", 130, 120), _w("NAME", 180, 120),
    _w("BEGINNING", 250, 120), _w("WITH", 340, 120), _w("SURNAME", 390, 120),
    _w("LOANA", 10, 150, conf=0.82), _w("GIRISHKUMAR", 80, 150, conf=0.84), _w("GHANASHAM", 200, 150, conf=0.81),
    # Marks
    _w("MAXIMUM", 10, 210), _w("MARKS", 100, 210),
    _w("100", 200, 210), _w("100", 260, 210), _w("100", 320, 210),
    _w("150", 380, 210), _w("150", 440, 210), _w("100", 500, 210),
    _w("700", 560, 210),
    _w("MARKS", 10, 250), _w("OBTAINED", 80, 250),
    _w("035", 200, 250), _w("047", 260, 250), _w("035", 320, 250),
    _w("052", 380, 250), _w("057", 440, 250), _w("035", 500, 250),
    _w("261", 560, 250),
    # Percentage (OCR may split "37.28" as "37 28")
    _w("PERCENTAGE", 620, 210),
    _w("37.28", 620, 250, conf=0.80),
    # Result
    _w("RESULT", 720, 210),
    _w("PASS", 720, 250, conf=0.88),
]


class TestSSC1988:
    def test_name(self):
        fields = _run_pipeline(SSC_1988_WORDS)
        name = _val(fields, "name")
        assert name is not None, "Name not extracted"
        assert "LOANA" in str(name).upper() or "GIRISHKUMAR" in str(name).upper(), \
            f"Wrong name: {name}"

    def test_percentage(self):
        fields = _run_pipeline(SSC_1988_WORDS)
        pct = _val(fields, "percentage")
        assert pct is not None, "Percentage not extracted"
        assert abs(float(pct) - 37.28) < 1.0, f"Wrong percentage: {pct}"

    def test_result(self):
        fields = _run_pipeline(SSC_1988_WORDS)
        result = _val(fields, "result")
        assert result == "PASS", f"Wrong result: {result}"


# ─────────────────────────────────────────────────────────────────────
# MARKSHEET 5: HSC 2022 Certificate — Jadhav Aditya Bhagvan, DISTINCTION
# ─────────────────────────────────────────────────────────────────────
HSC_2022_CERT_WORDS = [
    _w("HIGHER", 100, 10), _w("SECONDARY", 200, 10),
    _w("CERTIFICATE", 340, 10), _w("EXAMINATION", 470, 10), _w("CERTIFICATE", 600, 10),
    _w("This", 10, 60), _w("is", 50, 60), _w("to", 70, 60), _w("certify", 90, 60), _w("that", 150, 60),
    _w("Jadhav", 10, 90, conf=0.96), _w("Aditya", 90, 90, conf=0.97), _w("Bhagvan", 165, 90, conf=0.95),
    _w("CANDIDATE'S", 10, 120), _w("MOTHER'S", 120, 120), _w("NAME", 210, 120),
    _w("Nita", 350, 120, conf=0.91),
    _w("KOLHAPUR", 10, 150),
    _w("SEAT", 10, 175), _w("NO.", 60, 175), _w("X006102", 100, 175),
    _w("MARCH-2022", 300, 175),
    # Grade section
    _w("I-DIST", 200, 210, conf=0.92),
    _w("with", 270, 210), _w("subjects", 310, 210), _w("shown", 380, 210), _w("below.", 440, 210),
    # Subject marks
    _w("01", 10, 250), _w("ENGLISH", 50, 250), _w("ENG", 200, 250), _w("100", 280, 250), _w("063", 360, 250),
    _w("39", 10, 280), _w("GEOGRAPHY", 50, 280), _w("MAR", 200, 280), _w("100", 280, 280), _w("087", 360, 280),
    _w("54", 10, 310), _w("PHYSICS", 50, 310), _w("ENG", 200, 310), _w("100", 280, 310), _w("071", 360, 310),
    _w("55", 10, 340), _w("CHEMISTRY", 50, 340), _w("ENG", 200, 340), _w("100", 280, 340), _w("066", 360, 340),
    _w("56", 10, 370), _w("BIOLOGY", 50, 370), _w("ENG", 200, 370), _w("100", 280, 370), _w("068", 360, 370),
    _w("97", 10, 400), _w("INFORMATION", 50, 400), _w("TECHNOLOGY(SCI)", 160, 400), _w("ENG", 280, 400), _w("100", 360, 400), _w("096", 440, 400),
    # Total & Percentage
    _w("टकेवारी/", 10, 440), _w("Percentage", 100, 440),
    _w("75.17", 250, 440, conf=0.96),
    _w("एकूण", 350, 440), _w("गुण/Total", 430, 440), _w("Marks", 530, 440),
    _w("600", 620, 440, conf=0.96), _w("451", 700, 440, conf=0.95),
    # QR/cert serial (must be rejected)
    _w("CH225006980", 200, 520, conf=0.71),
    _w("4513399945898", 10, 545, conf=0.68),
]


class TestHSC2022Certificate:
    def test_name(self):
        fields = _run_pipeline(HSC_2022_CERT_WORDS)
        name = _val(fields, "name")
        assert name is not None, "Name not extracted"
        assert "jadhav" in str(name).lower() or "aditya" in str(name).lower(), \
            f"Wrong name: {name}"

    def test_percentage(self):
        fields = _run_pipeline(HSC_2022_CERT_WORDS)
        pct = _val(fields, "percentage")
        assert pct is not None, "Percentage not extracted"
        assert abs(float(pct) - 75.17) < 0.5, f"Wrong percentage: {pct}"

    def test_result_distinction(self):
        fields = _run_pipeline(HSC_2022_CERT_WORDS)
        result = _val(fields, "result")
        assert result == "DISTINCTION", f"Wrong result: {result}"

    def test_serial_rejected(self):
        """CH225006980 must be rejected as hallucination."""
        from app.academic_engine.validation_engine.hallucination_detector import HallucinationDetector
        hd = HallucinationDetector()
        is_hal, _ = hd.is_hallucination("percentage", "CH225006980", 0.71)
        assert is_hal, "CH225006980 should be hallucination"


# ─────────────────────────────────────────────────────────────────────
# NUMERIC REPAIR UNIT TESTS
# ─────────────────────────────────────────────────────────────────────
class TestNumericRepair:
    def setup_method(self):
        from app.academic_engine.validation_engine.numeric_repair import NumericRepair
        self.nr = NumericRepair()

    def test_space_split_decimal(self):
        val, rep = self.nr.repair("71 33", "percentage")
        assert val == "71.33", f"Expected 71.33, got {val}"

    def test_merged_decimal(self):
        val, rep = self.nr.repair("7517", "percentage")
        assert val == "75.17", f"Expected 75.17, got {val}"

    def test_grace_marks(self):
        val, rep = self.nr.repair("407+05", "obtained_marks")
        assert val == "412", f"Expected 412, got {val}"

    def test_currency_prefix(self):
        val, rep = self.nr.repair("£407+05", "obtained_marks")
        assert val == "412", f"Expected 412, got {val}"
