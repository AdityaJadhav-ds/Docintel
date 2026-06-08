"""
kv_renderer.py — Key-Value Block Renderer

Renders kv_block regions into structured key-value pairs.

A kv_block is a region where lines are in the form:
  "Key Label : value"
  "Key Label : value1  value2"

This is NOT a table. It should NEVER go through the table grid engine.
It renders as a list of {key, value} pairs with raw_lines fallback.
"""
import logging
from layout_tree import Region

logger = logging.getLogger(__name__)


def process_kv_region(kv_region: Region) -> dict:
    """
    Parse lines in a kv_block region into key-value pairs.

    Returns and stores in kv_region.content:
    {
        "pairs":     [{"key": str, "value": str}, ...],
        "raw_lines": [str, ...],   # always present for fallback
    }
    """
    raw_lines = [l.text for l in kv_region.lines]
    pairs = []

    for line in kv_region.lines:
        text = line.text.strip()
        if not text:
            continue

        if ":" in text:
            # Split on FIRST colon only
            k, _, v = text.partition(":")
            key   = k.strip()
            value = v.strip()
        else:
            # No colon — treat the whole line as a key with empty value
            key   = text
            value = ""

        if key:
            pairs.append({"key": key, "value": value})

    logger.debug(
        "kv_renderer: region %d → %d pairs from %d lines",
        kv_region.region_id, len(pairs), len(raw_lines)
    )

    result = {
        "pairs":     pairs,
        "raw_lines": raw_lines,
    }
    kv_region.content = result
    return result
