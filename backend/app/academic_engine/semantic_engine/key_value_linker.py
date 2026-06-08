"""
key_value_linker.py — STABILIZED
==================================
Finds field values near label nodes using the document graph.
Handles all 4 spatial relationships: right, below, same-line-after,
and embedded (label+value in same OCR token).

Covers Maharashtra SSC/HSC formats 1988–2022.
"""
import re


class KeyValueLinker:
    """Links field labels to their values using document graph relationships."""

    def __init__(self, graph):
        self.graph = graph

    def find_values_for_label(self, label_keywords: list) -> list:
        """
        For each node whose text contains a label keyword,
        collect candidate values from:
          1. nearest_right  (same row, value to the right of label)
          2. nearest_below  (value directly below label column)
          3. same-row siblings (scan right neighbours recursively up to 3 hops)
          4. inline extraction (label and value merged in one OCR token)
        """
        candidates = []
        seen_values = set()  # avoid duplicate candidates

        for node in self.graph.nodes:
            text_lower = node['text'].lower()
            matched_kw = None
            for kw in label_keywords:
                if kw in text_lower:
                    matched_kw = kw
                    break
            if not matched_kw:
                continue

            # ── Strategy 1: nearest right ──────────────────────
            right_id = node['relationships']['nearest_right']
            if right_id:
                right_node = self.graph.get_node(right_id)
                if right_node and right_node['text'] not in seen_values:
                    seen_values.add(right_node['text'])
                    candidates.append({
                        "value": right_node['text'],
                        "node": right_node,
                        "source_label": node['text'],
                        "strategy": "nearest_right",
                    })

            # ── Strategy 2: nearest below ──────────────────────
            below_id = node['relationships']['nearest_below']
            if below_id:
                below_node = self.graph.get_node(below_id)
                if below_node and below_node['text'] not in seen_values:
                    seen_values.add(below_node['text'])
                    candidates.append({
                        "value": below_node['text'],
                        "node": below_node,
                        "source_label": node['text'],
                        "strategy": "nearest_below",
                    })

            # ── Strategy 3: walk right 2 more hops ─────────────
            # Covers: "PERCENTAGE | 75 | .17" (two separate OCR tokens)
            hop_id = right_id
            for _ in range(2):
                if not hop_id:
                    break
                hop_node = self.graph.get_node(hop_id)
                if not hop_node:
                    break
                next_right_id = hop_node['relationships']['nearest_right']
                if next_right_id:
                    next_node = self.graph.get_node(next_right_id)
                    if next_node and next_node['text'] not in seen_values:
                        seen_values.add(next_node['text'])
                        candidates.append({
                            "value": next_node['text'],
                            "node": next_node,
                            "source_label": node['text'],
                            "strategy": "right_hop",
                        })
                hop_id = next_right_id

            # ── Strategy 4: inline extraction ──────────────────
            # Handles "PERCENTAGE 75.17" or "Percentage £82.40" in one token
            inline = self._extract_inline(node['text'], label_keywords)
            if inline and inline not in seen_values:
                seen_values.add(inline)
                candidates.append({
                    "value": inline,
                    "node": node,
                    "source_label": node['text'],
                    "strategy": "inline",
                })

        return candidates

    def _extract_inline(self, text: str, keywords: list) -> str:
        """
        If the OCR merged label+value into one token (e.g. "Percentage75.17"),
        extract just the value portion.
        """
        t = str(text)
        # Remove keyword parts and see what's left
        cleaned = t
        for kw in keywords:
            cleaned = re.sub(re.escape(kw), '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" :/-|")

        # If what remains looks like a number or name, return it
        if cleaned and cleaned != t.strip():
            return cleaned if len(cleaned) > 0 else None
        return None
