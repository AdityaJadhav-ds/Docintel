import re

class SemanticValidators:
    """Strict validators grounded in Maharashtra Board marksheet formats (SSC/HSC)."""

    # Serial/barcode patterns that must NEVER be mistaken for a percentage
    # e.g. H225007404, CS205008392, CH225006980, A-305732, F073951
    _SERIAL_PATTERN = re.compile(
        r'^[A-Z]{0,3}\d{6,}$'          # pure serial: H225007404
        r'|^[A-Z][-]\d{5,}$'           # dash serial: A-305732
        r'|^[A-Z]{2}\d{9,}$'           # long: 3713399945898
        r'|\d{10,}',                    # any 10+ digit number
        re.IGNORECASE
    )

    @staticmethod
    def is_valid_percentage(text: str) -> bool:
        """
        Valid percentage: a decimal number 0–100.
        Rules:
          - Must match XX.XX or XX format
          - Must NOT be a serial/barcode number
          - Must NOT have more than 3 digits before the decimal
        """
        t = str(text).strip()

        # Immediately reject serials / barcodes
        if SemanticValidators._SERIAL_PATTERN.search(t):
            return False

        # Must find a proper decimal percentage
        match = re.search(r'\b(\d{1,3})(?:\.(\d{1,2}))?\b', t)
        if not match:
            return False

        int_part = int(match.group(1))
        # More than 3 digits before decimal = not a percentage
        if len(str(int_part)) > 3:
            return False

        val = float(match.group(0).replace(' ', ''))
        return 0.0 <= val <= 100.0

    @staticmethod
    def is_valid_cgpa(text: str) -> bool:
        match = re.search(r'(\d{1,2}(?:\.\d{1,2})?)', str(text))
        if not match:
            return False
        val = float(match.group(1))
        return 0.0 <= val <= 10.0

    @staticmethod
    def is_board_or_university(text: str) -> bool:
        text_lower = text.lower()
        bad_words = [
            'board', 'university', 'examination', 'marksheet', 'institute',
            'school', 'college', 'council', 'certificate', 'education',
            'divisional', 'secondary', 'maharashtra', 'state', 'pune',
            'msbshse', 'kolhapur', 'mumbai', 'nashik', 'aurangabad',
        ]
        return any(b in text_lower for b in bad_words)

    @staticmethod
    def extract_percentage_number(text: str):
        """Extract actual float from a percentage string. Returns None if not valid."""
        t = str(text).strip()
        if SemanticValidators._SERIAL_PATTERN.search(t):
            return None
        match = re.search(r'\b(\d{1,3}(?:\.\d{1,2})?)\b', t)
        if not match:
            return None
        val = float(match.group(1))
        if 0.0 <= val <= 100.0:
            return val
        return None
