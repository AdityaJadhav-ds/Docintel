"""
test_active_learning_geometry.py
================================
Phase 4.2: Validates that active learning properly captures geometry fingerprints
and uses structural error classes instead of just string differences.
"""
import json
from app.extraction.active_learning import store_correction, get_corrections

def test_structural_error_classification():
    # Test that action_type=merge_row generates 'under_consolidation'
    rec = store_correction(
        run_id="test_run",
        block_id="test_block",
        original="Part A",
        corrected="Part A Part B",
        action_type="merge_row"
    )
    assert rec.error_class == "under_consolidation"
    
    rec2 = store_correction(
        run_id="test_run",
        block_id="test_block",
        original="Row 1",
        corrected="Row 2",
        action_type="relink_cell"
    )
    assert rec2.error_class == "orphan_value"

def test_geometry_fingerprint_persistence():
    dummy_fingerprints = {
        "layout_signature": "dense_table",
        "table_signature": "3_cols_sparse",
        "neighbor_signature": "header_above"
    }
    dummy_context = {
        "x1": 100, "y1": 200, "width": 500, "height": 50
    }
    
    rec = store_correction(
        run_id="test_run_persist",
        block_id="persist_block",
        original="100.00",
        corrected="1,000.00",
        action_type="update_boundary",
        geometry_context=dummy_context,
        geometry_fingerprints=dummy_fingerprints
    )
    
    assert rec.error_class == "table_boundary_violation"
    
    # Verify retrieval
    stored = get_corrections(limit=10)
    found = [r for r in stored if r.run_id == "test_run_persist"]
    assert len(found) > 0
    
    db_rec = found[0]
    assert db_rec.action_type == "update_boundary"
    
    # Geometry data is saved as stringified JSON in SQLite
    gc = json.loads(db_rec.geometry_context)
    gf = json.loads(db_rec.geometry_fingerprints)
    
    assert gc["width"] == 500
    assert gf["layout_signature"] == "dense_table"
