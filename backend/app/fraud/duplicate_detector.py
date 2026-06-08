"""
app/fraud/duplicate_detector.py — Cross-user duplicate identity detection
=========================================================================
Detects:
  1. Image duplicates — same/similar document photo reused by different users
  2. ID number reuse — same Aadhaar/PAN registered to multiple users
  3. Near-duplicate images — resized/rotated versions of same document

Uses image_hashing for visual comparison and Supabase for ID-level checks.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.fraud.image_hashing import (
    compute_all_hashes, hamming_distance, similarity_score,
    classify_hash_match, HashThreshold,
)


# ── Hash store/retrieve ───────────────────────────────────────────────────────

def store_image_hash(
    user_id:     int,
    document_id: Optional[int],
    doc_type:    str,
    image_input,
    file_size_kb: float = 0,
    width_px:    int = 0,
    height_px:   int = 0,
) -> Optional[Dict]:
    """Compute and persist image hashes to DB."""
    hashes = compute_all_hashes(image_input)
    payload = {
        "user_id":     user_id,
        "document_id": document_id,
        "doc_type":    doc_type,
        "phash":       hashes["phash"],
        "ahash":       hashes["ahash"],
        "dhash":       hashes["dhash"],
        "file_size_kb": round(file_size_kb, 2),
        "width_px":    width_px,
        "height_px":   height_px,
    }
    try:
        sb  = get_supabase()
        res = sb.table("image_hashes").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.error("[duplicate_detector] store_image_hash error: %s", exc)
        return None


def _fetch_all_hashes(exclude_user_id: int) -> List[Dict]:
    """Fetch all stored image hashes EXCEPT the current user."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("image_hashes")
            .select("user_id, document_id, doc_type, phash, ahash, dhash")
            .neq("user_id", exclude_user_id)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[duplicate_detector] _fetch_all_hashes error: %s", exc)
        return []


# ── Image duplicate search ────────────────────────────────────────────────────

def find_image_duplicates(
    image_input,
    user_id: int,
    phash_threshold: int = HashThreshold.NEAR_DUPLICATE,
) -> List[Dict]:
    """
    Compare current image hashes against all stored hashes.
    Returns list of matches with similarity scores.
    """
    current_hashes = compute_all_hashes(image_input)
    all_stored     = _fetch_all_hashes(exclude_user_id=user_id)
    matches: List[Dict] = []

    for stored in all_stored:
        # Compare pHash (most robust)
        p_dist = hamming_distance(current_hashes["phash"], stored.get("phash", ""))
        a_dist = hamming_distance(current_hashes["ahash"], stored.get("ahash", ""))
        d_dist = hamming_distance(current_hashes["dhash"], stored.get("dhash", ""))

        # Use minimum distance across all hash types
        min_dist    = min(p_dist, a_dist, d_dist)
        match_class = classify_hash_match(min_dist)
        sim_score   = similarity_score(current_hashes["phash"], stored.get("phash", ""))

        if min_dist <= phash_threshold:
            matches.append({
                "match_type":       "IMAGE_HASH",
                "match_class":      match_class,
                "similarity_score": sim_score,
                "hamming_distance": min_dist,
                "matched_user_id":  stored.get("user_id"),
                "matched_doc_id":   stored.get("document_id"),
                "matched_doc_type": stored.get("doc_type"),
            })
            logger.warning(
                "[duplicate_detector] Image duplicate: user=%s matches user=%s dist=%d class=%s",
                user_id, stored.get("user_id"), min_dist, match_class
            )

    return matches


# ── ID number duplicate search ────────────────────────────────────────────────

def find_id_duplicates(
    user_id:        int,
    aadhaar_number: Optional[str] = None,
    pan_number:     Optional[str] = None,
) -> List[Dict]:
    """
    Check if the same Aadhaar/PAN has been used by another user.
    Looks in extracted_data table.
    """
    import re
    matches: List[Dict] = []
    sb = get_supabase()

    if aadhaar_number:
        normalized = re.sub(r"\s", "", aadhaar_number)
        try:
            res = (
                sb.table("extracted_data")
                .select("user_id, doc_type, aadhaar_number")
                .neq("user_id", user_id)
                .execute()
            )
            for row in (res.data or []):
                stored_num = re.sub(r"\s", "", row.get("aadhaar_number") or "")
                if stored_num == normalized and stored_num:
                    matches.append({
                        "match_type":       "AADHAAR_NUMBER",
                        "match_field":      "aadhaar_number",
                        "match_class":      "IDENTICAL",
                        "similarity_score": 100,
                        "matched_user_id":  row.get("user_id"),
                        "matched_doc_type": row.get("doc_type"),
                    })
                    logger.warning(
                        "[duplicate_detector] Aadhaar collision: %s used by user %s AND %s",
                        aadhaar_number, user_id, row.get("user_id")
                    )
        except Exception as exc:
            logger.error("[duplicate_detector] Aadhaar lookup error: %s", exc)

    if pan_number:
        try:
            res = (
                sb.table("extracted_data")
                .select("user_id, doc_type, pan_number")
                .neq("user_id", user_id)
                .execute()
            )
            for row in (res.data or []):
                if (row.get("pan_number") or "").upper() == pan_number.upper():
                    matches.append({
                        "match_type":       "PAN_NUMBER",
                        "match_field":      "pan_number",
                        "match_class":      "IDENTICAL",
                        "similarity_score": 100,
                        "matched_user_id":  row.get("user_id"),
                        "matched_doc_type": row.get("doc_type"),
                    })
                    logger.warning(
                        "[duplicate_detector] PAN collision: %s used by user %s AND %s",
                        pan_number, user_id, row.get("user_id")
                    )
        except Exception as exc:
            logger.error("[duplicate_detector] PAN lookup error: %s", exc)

    return matches


# ── Save duplicate matches ────────────────────────────────────────────────────

def save_duplicate_matches(source_user_id: int, matches: List[Dict]) -> None:
    """Persist all duplicate matches to DB."""
    if not matches:
        return
    sb      = get_supabase()
    payload = []
    for m in matches:
        payload.append({
            "source_user_id":  source_user_id,
            "target_user_id":  m.get("matched_user_id"),
            "match_type":      m.get("match_type"),
            "match_field":     m.get("match_field"),
            "similarity_score": m.get("similarity_score", 100),
        })
    try:
        sb.table("duplicate_matches").insert(payload).execute()
    except Exception as exc:
        logger.error("[duplicate_detector] save_duplicate_matches error: %s", exc)


# ── Duplicate risk score ──────────────────────────────────────────────────────

def compute_duplicate_score(matches: List[Dict]) -> int:
    """
    0-100 duplicate risk score from match list.
    ID matches score higher than image similarity matches.
    """
    if not matches:
        return 0
    score = 0
    for m in matches:
        mt = m.get("match_type", "")
        mc = m.get("match_class", "")
        if mt in ("AADHAAR_NUMBER", "PAN_NUMBER"):
            score += 70      # critical: same ID = definite identity collision
        elif mc == "IDENTICAL":
            score += 60
        elif mc == "NEAR_DUPLICATE":
            score += 40
        elif mc == "SIMILAR":
            score += 20
    return min(100, score)


# ── Full duplicate analysis ───────────────────────────────────────────────────

def analyze_duplicates(
    image_input,
    user_id:        int,
    doc_type:       str,
    document_id:    Optional[int] = None,
    aadhaar_number: Optional[str] = None,
    pan_number:     Optional[str] = None,
    file_size_kb:   float = 0,
    width_px:       int = 0,
    height_px:      int = 0,
) -> Dict:
    """
    Full duplicate analysis: image hash + ID number checks.
    Stores hash and any matches found.

    Returns:
        {
            "duplicate_detected":  bool,
            "duplicate_score":     int (0-100),
            "duplicate_matches":   [...]
        }
    """
    # Store this image's hash first
    store_image_hash(user_id, document_id, doc_type, image_input,
                     file_size_kb, width_px, height_px)

    # Image-level duplicate check
    img_matches = find_image_duplicates(image_input, user_id)

    # ID-level duplicate check
    id_matches = find_id_duplicates(user_id, aadhaar_number, pan_number)

    all_matches = img_matches + id_matches
    dup_score   = compute_duplicate_score(all_matches)

    if all_matches:
        save_duplicate_matches(user_id, all_matches)

    return {
        "duplicate_detected": bool(all_matches),
        "duplicate_score":    dup_score,
        "duplicate_matches":  all_matches,
    }
