class SemanticSanity:
    """Step 8: Semantic Sanity Checks — STABILIZED.
    
    Rules:
    - NEVER crash on None values.
    - NEVER mutate fields dict.
    - Only appends warnings; never modifies anything.
    """

    def check_sanity(self, fields: dict, full_text: str) -> list:
        warnings = []

        # ── Name sanity ──────────────────────────────────────
        name_obj = fields.get('name')
        if name_obj and isinstance(name_obj, dict):
            name_val = name_obj.get('value')
            if name_val is not None:
                board_words = ['board', 'university', 'education', 'school']
                if any(b in str(name_val).lower() for b in board_words):
                    warnings.append("Name is semantically identical to a Board/Organization")

        # ── Percentage sanity ────────────────────────────────
        pct_obj = fields.get('percentage')
        if pct_obj and isinstance(pct_obj, dict):
            pct_val = pct_obj.get('value')
            if pct_val is not None:
                try:
                    num_str = "".join(c for c in str(pct_val) if c.isdigit() or c == '.')
                    if num_str and float(num_str) > 100.0:
                        warnings.append("Percentage mathematically exceeds 100")
                except ValueError:
                    pass

        # ── SPI / SSC mismatch ───────────────────────────────
        spi_obj = fields.get('spi')
        if spi_obj and isinstance(spi_obj, dict) and spi_obj.get('value') is not None:
            ft = str(full_text).lower()
            if 'secondary school certificate' in ft or ' ssc ' in ft:
                warnings.append("SPI found but document appears to be SSC. Highly suspicious.")

        return warnings
