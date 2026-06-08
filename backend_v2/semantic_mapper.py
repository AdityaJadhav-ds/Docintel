"""
semantic_mapper.py — Universal Semantic Column Mapper

Takes a grid (list of rows, each row is list of cell strings)
and tries to identify the column roles from the content itself.

NO bank names. NO document type assumptions. NO hardcoded indexes.
Works by inspecting the first row that looks like a header.
"""

import re
import logging

logger = logging.getLogger(__name__)

# ── Patterns for column role detection ────────────────────────────────────────
_DATE_PATTERN   = re.compile(r'\b\d{2}[/\-]\d{2}[/\-]\d{2,4}\b|\b\d{2}\s*[A-Za-z]{3}\s*\d{2,4}\b')
_AMOUNT_PATTERN = re.compile(r'^\d[\d,]*\.\d{2}$')
_REFNO_PATTERN  = re.compile(r'\b[A-Z0-9]{10,}\b')

# Known header keyword groups (case-insensitive, partial match)
_HEADER_KEYWORDS = {
    "date":        ["date", "dated", "txn date", "value date", "post date", "trans date"],
    "description": ["description", "particulars", "narration", "details", "remarks", "transaction"],
    "debit":       ["debit", "dr", "withdrawal", "dr.", "dr amount"],
    "credit":      ["credit", "cr", "deposit", "cr.", "cr amount"],
    "balance":     ["balance", "bal", "closing", "running balance"],
    "ref":         ["ref", "chq", "reference", "cheque", "utr", "txn id", "txn ref"],
}


def _score_header_cell(cell_text: str) -> str:
    """Return the semantic role of a header cell, or 'unknown'."""
    text = cell_text.lower().strip()
    for role, keywords in _HEADER_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return role
    return "unknown"


def _detect_header_row(grid: list) -> tuple:
    """
    Find which row in the grid is the header row.
    Heuristics: short cells, mostly alphabetic, matches known keywords.
    Returns (row_index, roles_list) or (-1, []).
    """
    best_row = -1
    best_score = 0

    for i, row in enumerate(grid[:6]):  # only check first 6 rows
        score = 0
        for cell in row:
            cell = cell.strip()
            if not cell:
                continue
            # Short cell (likely a label, not data)
            if len(cell) < 30:
                score += 1
            # Mostly letters
            if cell.replace(" ", "").isalpha():
                score += 2
            # Matches a keyword
            if _score_header_cell(cell) != "unknown":
                score += 4
        if score > best_score:
            best_score = score
            best_row = i

    if best_row < 0 or best_score < 3:
        return -1, []

    roles = [_score_header_cell(cell) for cell in grid[best_row]]
    return best_row, roles


def _infer_role_from_data(col_values: list) -> str:
    """
    When the header gives no clue, infer the column role from data values.
    """
    if not col_values:
        return "unknown"

    date_count   = sum(1 for v in col_values if _DATE_PATTERN.search(v))
    amount_count = sum(1 for v in col_values if _AMOUNT_PATTERN.match(v.replace(",", "")))
    ref_count    = sum(1 for v in col_values if _REFNO_PATTERN.search(v))
    total        = max(1, len([v for v in col_values if v.strip()]))

    if date_count / total > 0.5:
        return "date"
    if amount_count / total > 0.5:
        return "amount"
    if ref_count / total > 0.3:
        return "ref"
    return "description"


def map_columns(grid: list) -> dict:
    """
    Main entry point.
    Returns:
      {
        "header_row_index": int,   (-1 if not found)
        "roles":            list,  (one role string per column)
        "data_rows":        list,  (grid rows after header)
        "transactions":     list,  (list of {date, description, amount, balance, ref})
      }
    """
    if not grid:
        return {"header_row_index": -1, "roles": [], "data_rows": [], "transactions": []}

    header_idx, roles = _detect_header_row(grid)

    # If header not found, infer from first few data rows
    if header_idx < 0 or all(r == "unknown" for r in roles):
        data_rows = grid
        n_cols = max((len(row) for row in grid), default=0)
        roles = []
        for col_i in range(n_cols):
            col_values = [row[col_i] for row in grid[:20] if col_i < len(row)]
            roles.append(_infer_role_from_data(col_values))
        header_idx = -1
    else:
        data_rows = grid[header_idx + 1:]

    # Build transactions — only rows that contain at least one date value
    transactions = []
    for row in data_rows:
        row_text = " ".join(row)
        if not _DATE_PATTERN.search(row_text[:60]):  # date must appear early in row
            continue

        tx = {"date": "", "description": "", "amount": "", "balance": "", "ref": "", "raw": row_text}
        amounts_found = []

        for i, cell in enumerate(row):
            if i >= len(roles):
                break
            role = roles[i]
            cell = cell.strip()
            if not cell:
                continue

            if role == "date" and not tx["date"]:
                tx["date"] = cell
            elif role == "description":
                tx["description"] = (tx["description"] + " " + cell).strip()
            elif role in ("debit", "credit", "amount"):
                amounts_found.append(cell)
            elif role == "balance":
                tx["balance"] = cell
            elif role == "ref":
                tx["ref"] = cell
            elif role == "unknown":
                # Classify by content
                if not tx["date"] and _DATE_PATTERN.search(cell):
                    tx["date"] = cell
                elif _AMOUNT_PATTERN.match(cell.replace(",", "")):
                    amounts_found.append(cell)
                elif len(cell) > 4:
                    tx["description"] = (tx["description"] + " " + cell).strip()

        # Assign amounts: last amount = balance, second-to-last = debit/credit
        if amounts_found:
            if not tx["balance"]:
                tx["balance"] = amounts_found[-1]
            if len(amounts_found) >= 2 and not tx["amount"]:
                tx["amount"] = amounts_found[-2]
            elif len(amounts_found) == 1 and not tx["amount"] and not tx["balance"]:
                tx["amount"] = amounts_found[0]

        if tx["date"] or tx["description"]:
            transactions.append(tx)

    logger.info("semantic_mapper: header_row=%d roles=%s transactions=%d",
                header_idx, roles, len(transactions))

    return {
        "header_row_index": header_idx,
        "roles":            roles,
        "data_rows":        data_rows,
        "transactions":     transactions,
    }
