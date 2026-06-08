"""
test_graph_fuzzing.py
=====================
Phase 4.2: Fuzz testing for graph mutation integrity.
Generates randomized mutation sequences and verifies GraphInvariantEngine assertions.
"""
import random
import uuid
import pytest
from app.extraction.graph_mutator import mutate_graph, _SNAPSHOTS
from tests.test_graph_mutator import create_dummy_run
from tests.graph_invariant_engine import GraphInvariantEngine

def generate_random_mutation(blocks, layout_meta):
    """Generates a random valid/invalid mutation action."""
    action_types = ["merge_row", "split_row", "text_edit", "update_link", "mark_continuation"]
    action = random.choice(action_types)
    
    if not blocks:
        return action, {}
        
    b1 = random.choice(blocks)
    b2 = random.choice(blocks)
    
    bid1 = str(b1.get("node_id", b1.get("id")))
    bid2 = str(b2.get("node_id", b2.get("id")))
    
    payload = {}
    if action == "merge_row":
        payload = {"source_id": bid1, "target_id": bid2}
    elif action == "split_row":
        # Random split point that could be valid or completely invalid
        split_x = b1.get("x1", 0) + random.uniform(-100, b1.get("width", 100) + 100)
        payload = {"block_id": bid1, "split_x": split_x}
    elif action == "text_edit":
        payload = {"block_id": bid1, "corrected_text": "Fuzzed text"}
    elif action == "update_link":
        payload = {"source_id": bid1, "target_id": bid2, "relation": "fuzz_link"}
    elif action == "mark_continuation":
        payload = {"block_id": bid1, "target_id": bid2}
        
    return action, payload

@pytest.mark.skip(reason="Fuzz test takes long to run in standard CI")
def test_fuzz_graph_mutations():
    """Run 1000 random mutations and ensure no graph invariants are ever permanently violated."""
    run = create_dummy_run()
    
    for _ in range(1000):
        # We need active blocks to mutate
        active_blocks = [b for b in run.result["blocks"] if not b.get("_deleted")]
        if len(active_blocks) < 2:
            # Recreate dummy graph if it got too small
            run = create_dummy_run()
            active_blocks = [b for b in run.result["blocks"] if not b.get("_deleted")]
            
        action, payload = generate_random_mutation(active_blocks, run.result["layout_meta"])
        
        # Dispatch mutation
        res = mutate_graph(run.run_id, action, payload)
        
        # If accepted, we absolutely MUST pass invariant checks.
        # If rejected, it rolled back, so we should ALSO pass invariant checks.
        try:
            GraphInvariantEngine.validate_all(run.result["blocks"], run.result["layout_meta"])
        except Exception as e:
            pytest.fail(f"Fuzz test broken invariant after {action} with {payload}. Error: {e}")
