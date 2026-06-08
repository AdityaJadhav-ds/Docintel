import re

class ConsistencyChecker:
    """Step 2: Cross-check extracted fields — STABILIZED.
    
    Rules:
    - NEVER crash on None values.
    - NEVER mutate fields dict.
    - Only appends warnings.
    """

    def check_consistency(self, fields: dict) -> list:
        inconsistencies = []

        pct_obj     = fields.get('percentage')
        spi_obj     = fields.get('spi') or fields.get('cgpa')
        obtained_obj = fields.get('obtained_marks')
        total_obj   = fields.get('total_marks')

        # ── SPI vs Percentage ────────────────────────────────
        if pct_obj and spi_obj:
            pct_val = self._extract_num(pct_obj.get('value'))
            spi_val = self._extract_num(spi_obj.get('value'))
            if pct_val is not None and spi_val is not None:
                if pct_val <= 10.0 and spi_val <= 10.0:
                    inconsistencies.append(
                        "Percentage and SPI are both scaled to 10. One is misclassified."
                    )

        # ── Marks consistency ────────────────────────────────
        if obtained_obj and total_obj:
            obt_val = self._extract_num(obtained_obj.get('value'))
            tot_val = self._extract_num(total_obj.get('value'))
            if obt_val is not None and tot_val is not None:
                if obt_val > tot_val:
                    inconsistencies.append("Obtained marks greater than Total marks.")

                # Math cross-check with percentage
                if pct_obj and tot_val > 0:
                    pct_val = self._extract_num(pct_obj.get('value'))
                    if pct_val is not None:
                        calculated_pct = (obt_val / tot_val) * 100
                        if abs(calculated_pct - pct_val) > 1.0:
                            inconsistencies.append(
                                f"Percentage inconsistent with marks. "
                                f"Found {pct_val}, expected ~{calculated_pct:.2f}"
                            )

        return inconsistencies

    def _extract_num(self, text):
        """Safely parse a number from a string or None."""
        if text is None:
            return None
        match = re.search(r'(\d+(?:\.\d+)?)', str(text))
        if match:
            return float(match.group(1))
        return None
