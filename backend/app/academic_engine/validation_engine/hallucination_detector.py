"""
hallucination_detector.py — STABILIZED
========================================
Catches common OCR hallucinations specific to Maharashtra marksheets.

Known hallucinations observed:
  - H225007404  (barcode serial near HSC 2022 percentage)
  - CS205008392 (QR code serial near SSC 2020 certificate)
  - 3713399945898  (13-digit product barcode)
  - F261829 / F073951  (seat number being extracted as percentage)
  - MSBSHSE  (board abbreviation near name field)
"""
import re


class HallucinationDetector:
    """Detects impossible or nonsensical field values."""

    # Patterns that are NEVER valid field values (barcodes, serials, cert numbers)
    _SERIAL_PATTERNS = [
        re.compile(r'^[A-Z]{1,3}\d{6,}$', re.IGNORECASE),  # H225007404, CS205008392
        re.compile(r'^\d{10,}$'),                            # 3713399945898
        re.compile(r'^[A-Z]-\d{5,}$', re.IGNORECASE),       # A-305732
        re.compile(r'^[A-Z]{2}\d{4,}[A-Z]?\d+$', re.IGNORECASE),  # F073951, X006102
    ]

    def is_hallucination(self, field_name: str, value, confidence: float) -> tuple:
        if value is None:
            return False, "None value"

        value_str = str(value).strip()

        # ── Universal: very low confidence ────────────────────
        if confidence < 0.15:
            return True, "Extremely low confidence, likely garbage"

        # ── Universal: no alphanumeric content ────────────────
        if len(value_str) > 3 and not any(c.isalnum() for c in value_str):
            return True, "Contains no alphanumeric characters"

        # ── Percentage-specific hallucinations ─────────────────
        if field_name == 'percentage':
            # Serial/barcode patterns near percentage label
            for pat in self._SERIAL_PATTERNS:
                if pat.match(value_str):
                    return True, f"Looks like a serial/barcode number: {value_str}"

            # More than 3 digits before decimal = impossible percentage
            m = re.match(r'^(\d+)', value_str)
            if m and len(m.group(1)) > 3:
                return True, f"Integer part too long for percentage: {value_str}"

            # Try to parse the number itself
            try:
                # Strip % sign
                num = float(re.sub(r'[^\d.]', '', value_str))
                if num > 100.0:
                    return True, f"Percentage > 100: {num}"
                if num < 0.0:
                    return True, f"Negative percentage: {num}"
            except ValueError:
                pass  # Let field_validator handle non-numeric

        # ── Total marks ────────────────────────────────────────
        elif field_name == 'total_marks':
            digits = "".join(filter(str.isdigit, value_str))
            if digits and int(digits) > 5000:
                return True, f"Impossible total marks: {digits}"

        # ── Name-specific hallucinations ───────────────────────
        elif field_name == 'name':
            # No vowels in a long string = OCR noise
            vowels = set("AEIOUaeiouAEIOUaeiou")
            if len(value_str) > 6 and not any(v in value_str for v in vowels):
                return True, "Name contains no vowels, likely hallucination"

            # Pure numbers are never names
            if value_str.replace(' ', '').isdigit():
                return True, "Name is all digits"

            # Board/serial patterns in name
            for pat in self._SERIAL_PATTERNS:
                if pat.match(value_str.replace(' ', '')):
                    return True, f"Name looks like serial number: {value_str}"

        return False, "Seems real"
