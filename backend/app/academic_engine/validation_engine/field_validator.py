"""
field_validator.py — STABILIZED
=================================
Validates individual extracted field values.
Tuned for Maharashtra SSC/HSC marksheet formats.
"""
import re


class FieldValidator:
    """Validates every field independently. Returns (is_valid, error_message)."""

    @staticmethod
    def validate_name(value, confidence: float) -> tuple:
        if confidence < 0.25:
            return False, "Confidence too low for name"

        t = str(value).strip()
        if not t:
            return False, "Empty name"

        # Organisational keywords must not appear
        bad_words = [
            'board', 'university', 'exam', 'marksheet', 'institute',
            'divisional', 'secondary', 'maharashtra', 'msbshse', 'school',
        ]
        t_lower = t.lower()
        if any(b in t_lower for b in bad_words):
            return False, "Contains organisational keyword"

        # Too many digits
        digit_count = sum(c.isdigit() for c in t)
        if digit_count > 2:
            return False, f"Too many digits in name: {digit_count}"

        # Too short to be a real name
        if len(t.replace(' ', '')) < 3:
            return False, "Name too short"

        return True, "Valid"

    @staticmethod
    def validate_percentage(value) -> tuple:
        if value is None:
            return False, "No value"

        t = str(value).strip()

        # Strip any % sign before parsing
        t_clean = t.replace('%', '').strip()

        # Reject serial patterns immediately
        if re.search(r'[A-Z]\d{6,}', t_clean, re.IGNORECASE):
            return False, f"Looks like serial number: {t_clean}"
        if re.search(r'\d{8,}', t_clean):
            return False, f"Too many digits: {t_clean}"

        # Extract the actual decimal number
        # Handles "75.17", "71 33" (space OCR artifact), "82.40", "37.28"
        # Also handles "£407+05" → reject (that's marks not percentage)
        m = re.search(r'\b(\d{1,3})(?:[.\s](\d{1,2}))?\b', t_clean)
        if not m:
            return False, f"No valid number found in: {t_clean}"

        int_part = int(m.group(1))
        dec_part = m.group(2) or "0"

        # More than 3 digits before decimal = not a percentage
        if len(str(int_part)) > 3:
            return False, f"Integer part too large: {int_part}"

        num = float(f"{int_part}.{dec_part}")
        if 0.0 <= num <= 100.0:
            return True, "Valid"

        return False, f"Out of bounds: {num}"

    @staticmethod
    def validate_cgpa(value) -> tuple:
        if value is None:
            return False, "No value"
        m = re.search(r'(\d{1,2}(?:\.\d{1,2})?)', str(value))
        if not m:
            return False, "No valid number found"
        num = float(m.group(1))
        if 0.0 <= num <= 10.0:
            return True, "Valid"
        return False, f"Out of bounds: {num}"

    @staticmethod
    def validate_year(value) -> tuple:
        if value is None:
            return False, "No value"
        m = re.search(r'(\d{4})', str(value))
        if not m:
            return False, "No year found"
        year = int(m.group(1))
        if 1980 <= year <= 2035:
            return True, "Valid"
        return False, "Year out of bounds"

    @staticmethod
    def validate_result(value) -> tuple:
        if value is None:
            return False, "No value"
        valid_results = ['PASS', 'FAIL', 'DISTINCTION', 'FIRST CLASS', 'SECOND CLASS']
        value_upper = str(value).upper()
        if any(v in value_upper for v in valid_results):
            return True, "Valid"
        return False, f"Unknown result text: {value}"

    @staticmethod
    def validate_marks(value) -> tuple:
        """Validate obtained_marks or total_marks."""
        if value is None:
            return False, "No value"
        # Strip grace mark notation like "407+05" → take base
        t = str(value).strip()
        t_clean = re.sub(r'[£$+]\d+', '', t).strip()
        m = re.search(r'(\d{2,4})', t_clean)
        if not m:
            return False, f"No numeric marks found: {t}"
        num = float(m.group(1))
        if 0.0 <= num <= 10000.0:
            return True, "Valid"
        return False, f"Marks out of bounds: {num}"
