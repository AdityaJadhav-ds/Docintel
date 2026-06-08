"""
line_engine.py — Adaptive Line Builder

Groups ordered Words into Line objects using:
  - Adaptive Y-band tolerance: median_word_height * 0.70
    (NOT a fixed threshold — scales with font size per page)
  - Left-to-right word sort within each line
  - Line text = space-joined words

Adaptive tolerance means dense bank-statement fonts (height ~14px)
get a 10px band, while large header fonts (height ~40px) get a 28px
band — preventing both line collisions AND line splits.
"""
import numpy as np
from layout_tree import Word, Line
from reading_order import sort_reading_order

# Band multiplier: 0.70 of median word height.
# - Too low (0.4): splits multiline headers / wide-spaced text
# - Too high (0.9): merges adjacent lines in dense tables
Y_BAND_FACTOR = 0.70
Y_BAND_MIN    = 3.0   # never narrower than 3px regardless of font
Y_BAND_MAX    = 30.0  # never wider than 30px (prevents cross-row merges)


def build_lines(words: list[Word]) -> list[Line]:
    """
    Groups words into visual lines.
    Tolerance adapts to the median word height on this page.
    """
    if not words:
        return []

    ordered = sort_reading_order(words)

    # Compute adaptive tolerance from ALL words on the page
    heights = [w.height for w in ordered if w.height > 0]
    if heights:
        median_h = float(np.median(heights))
    else:
        median_h = 12.0

    tol = float(np.clip(median_h * Y_BAND_FACTOR, Y_BAND_MIN, Y_BAND_MAX))

    lines: list[Line] = []
    current_words = [ordered[0]]
    current_y     = ordered[0].cy
    line_id       = 0

    for w in ordered[1:]:
        if abs(w.cy - current_y) <= tol:
            # Same line — update rolling Y mean
            current_words.append(w)
            current_y = float(np.mean([x.cy for x in current_words]))
        else:
            lines.append(_make_line(line_id, current_words))
            line_id += 1
            current_words = [w]
            current_y     = w.cy

    if current_words:
        lines.append(_make_line(line_id, current_words))

    # Stage 3: Merge multiline wrapped blocks based on geometry & indentation
    page_left_margin = min(l.x1 for l in lines) if lines else 0.0
    median_h_lines = float(np.median([l.cy - lines[i-1].cy for i, l in enumerate(lines) if i > 0 and l.cy > lines[i-1].cy])) if len(lines) > 1 else 15.0

    return _merge_multiline_blocks(lines, page_left_margin, median_h_lines)

def _merge_multiline_blocks(lines: list[Line], page_margin: float, line_spacing: float) -> list[Line]:
    """
    Second pass: detects wrapped text (e.g. multi-line narration in a cell)
    by pure X-alignment and indentation, merging them into logical rows.
    """
    if not lines:
        return []

    merged = []
    
    def _create_logical(base_line: Line) -> Line:
        return Line(
            line_id=base_line.line_id,
            words=list(base_line.words),
            text=base_line.text,
            x1=base_line.x1, y1=base_line.y1, x2=base_line.x2, y2=base_line.y2, cy=base_line.cy,
            visual_lines=[base_line]
        )
        
    current_logical = _create_logical(lines[0])

    # Indent threshold: wrapped text usually doesn't start at the very left edge
    indent_threshold = 20.0 

    for next_line in lines[1:]:
        # Vertical gap check
        vert_gap = next_line.y1 - current_logical.y2
        gap_small = vert_gap < (line_spacing * 1.5)

        # Indentation check
        is_indented = next_line.x1 > (page_margin + indent_threshold)

        # Overlap check
        overlap = not (next_line.x2 < current_logical.x1 or next_line.x1 > current_logical.x2)

        # Stronger bias for short lines
        word_count = len(next_line.words)
        is_short = word_count < 5

        # Heuristic
        if is_indented and overlap and gap_small and (is_short or next_line.x1 >= current_logical.x1):
            # Merge!
            current_logical.visual_lines.append(next_line)
            # Update logical row bounds
            current_logical.x1 = min(current_logical.x1, next_line.x1)
            current_logical.x2 = max(current_logical.x2, next_line.x2)
            current_logical.y2 = max(current_logical.y2, next_line.y2)
            current_logical.cy = (current_logical.y1 + current_logical.y2) / 2
            current_logical.words.extend(next_line.words)
            current_logical.text += " " + next_line.text
        else:
            # Finalize logical row and start a new one
            merged.append(current_logical)
            current_logical = _create_logical(next_line)

    merged.append(current_logical)
    
    # Re-assign line IDs to be contiguous
    for i, m in enumerate(merged):
        m.line_id = i
        
    return merged


def _make_line(line_id: int, words: list[Word]) -> Line:
    """Creates a Line from a group of words, sorted left→right."""
    words_lr = sorted(words, key=lambda w: w.x1)
    text = " ".join(w.text for w in words_lr if w.text)
    x1 = min(w.x1 for w in words_lr)
    x2 = max(w.x2 for w in words_lr)
    y1 = min(w.y1 for w in words_lr)
    y2 = max(w.y2 for w in words_lr)
    cy = float(np.mean([w.cy for w in words_lr]))

    return Line(
        line_id=line_id,
        words=words_lr,
        text=text,
        x1=x1, y1=y1, x2=x2, y2=y2, cy=cy,
    )
