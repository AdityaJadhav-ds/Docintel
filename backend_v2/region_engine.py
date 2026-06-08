"""
region_engine.py — Smart Region Classifier

Assigns a region_type to each Line (logical row).
Types: "header", "kv_block", "table", "footer"

Rules:
- Table: Dense rows (many words/columns spread out) or rows with numbers.
- Header: Top of page, fewer words, large fonts.
- Footer: Bottom of page.
- KV Block: Rows with colon ":" or sparse key-value structures.
"""
from layout_tree import Line, Page

def assign_regions(page: Page):
    """
    Classifies each line in the page into a region type.
    We just assign line.region_type so the frontend can use it for Smart Hybrid Mode.
    """
    if not page.lines:
        return

    # Basic page geometry
    page_h = page.height if page.height > 0 else 1600.0
    header_bottom = page_h * 0.18
    footer_top    = page_h * 0.90

    for line in page.lines:
        # Default
        line.region_type = "paragraph"

        word_count = len(line.words)
        has_colon = ":" in line.text
        
        # Check for numbers which highly correlate with tables/ledgers
        num_count = sum(1 for w in line.words if any(c.isdigit() for c in w.text))

        # Spread: how much of the page width does this line span?
        width_ratio = (line.x2 - line.x1) / page.width if page.width > 0 else 0

        # Heuristics
        if line.cy < header_bottom:
            line.region_type = "header"
            if has_colon:
                line.region_type = "kv_block"
        elif line.cy > footer_top:
            line.region_type = "footer"
        else:
            # Body area
            if word_count > 5 and width_ratio > 0.4 and num_count >= 2:
                line.region_type = "table"
            elif word_count > 3 and num_count >= 1 and (line.x2 - line.x1) > 200:
                line.region_type = "table"
            elif has_colon:
                line.region_type = "kv_block"
            else:
                line.region_type = "paragraph"

    # Smoothing pass: if a paragraph is surrounded by table rows, it's likely a table row (or wrapped table cell)
    for i in range(1, len(page.lines) - 1):
        prev_t = page.lines[i-1].region_type
        curr_t = page.lines[i].region_type
        next_t = page.lines[i+1].region_type

        if curr_t == "paragraph" and prev_t == "table" and next_t == "table":
            page.lines[i].region_type = "table"
        
        # Also if the row is short but it's directly under a table row, it might be wrapped text in the table
        if curr_t == "paragraph" and prev_t == "table" and len(page.lines[i].words) < 5:
            page.lines[i].region_type = "table"
