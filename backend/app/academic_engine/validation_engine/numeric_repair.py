"""
numeric_repair.py — STABILIZED
================================
Repairs common OCR corruption in numeric fields.
Tuned for Maharashtra SSC/HSC marksheets:
  - Space-split decimals: "71 33" → "71.33"
  - Grace mark notation: "407+05" → "412" (add grace)
  - OCR character swaps: S→5, O→0, l→1, |→1
  - Missing decimal: "7517" → "75.17"
"""
import re


class NumericRepair:
    """Repairs OCR corruption in numeric fields."""

    def repair(self, text, field_type: str) -> tuple:
        if text is None:
            return text, False

        original = str(text).strip()
        t = original

        # ── Phase 1: OCR character substitutions ──────────────
        char_map = {
            'S': '5', 's': '5',
            'O': '0', 'o': '0',
            'l': '1', 'I': '1', '|': '1',
            '?': '7', 'Z': '2', 'z': '2',
            'B': '8', 'G': '6',
        }
        # Only apply substitutions if the result looks more numeric
        for bad, good in char_map.items():
            candidate = t.replace(bad, good)
            # Only accept if it removed non-numeric chars
            if sum(c.isdigit() for c in candidate) > sum(c.isdigit() for c in t):
                t = candidate

        # ── Phase 2: Field-specific repairs ───────────────────
        if field_type in ('percentage', 'cgpa', 'spi'):
            # First: extract just the leading numeric portion from mixed strings
            # e.g. "71 33 PASS" → "71 33", "£ 82.40" → "82.40"
            t = re.sub(r'[£$€₹%]', '', t).strip()

            # Remove trailing non-numeric words (e.g. "71 33 PASS" → "71 33")
            parts = t.split()
            numeric_parts = []
            for part in parts:
                if re.match(r'^\d+$', part):
                    numeric_parts.append(part)
                else:
                    break  # stop at first non-numeric word
            if len(numeric_parts) >= 2:
                # Could be space-split decimal: "71 33" → "71.33"
                candidate = f"{numeric_parts[0]}.{numeric_parts[1]}"
                try:
                    val = float(candidate)
                    if 0.0 <= val <= 100.0:
                        t = candidate
                except ValueError:
                    pass
            elif len(numeric_parts) == 1 and not t.replace('.', '').isdigit():
                t = numeric_parts[0]

            # Handle already-correct decimal "75.17" — keep as is
            m_already = re.match(r'^(\d{1,3}\.\d{1,2})$', t.strip())
            if m_already:
                return t.strip(), (t.strip() != original)

            # Handle "7517" → "75.17" (4-digit merged decimal)
            m = re.match(r'^(\d{2})(\d{2})$', t.strip())
            if m:
                val = float(f"{m.group(1)}.{m.group(2)}")
                if 0.0 <= val <= 100.0:
                    t = f"{m.group(1)}.{m.group(2)}"

            # Handle CGPA "895" → "8.95"
            if field_type in ('cgpa', 'spi'):
                m = re.match(r'^(\d{1})(\d{2})$', t.strip())
                if m:
                    t = f"{m.group(1)}.{m.group(2)}"

        elif field_type in ('total_marks', 'obtained_marks'):
            # Strip £/$ prefix FIRST (SSC 2020 cert uses £ before marks)
            t = re.sub(r'^[£$€₹]\s*', '', t.strip())

            # Handle grace mark notation: "407+05" → 407+5=412
            m = re.match(r'^(\d{2,4})\s*\+\s*(\d{1,3})$', t.strip())
            if m:
                base = int(m.group(1))
                grace = int(m.group(2))
                t = str(base + grace)

            # Retain only the leading number
            m2 = re.search(r'^(\d{2,4})', t)
            if m2:
                t = m2.group(1)

        repaired = (t != original)
        return t, repaired
