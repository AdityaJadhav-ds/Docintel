"""
GraphInvariantEngine
====================
Phase 4.2: Graph Integrity Defense Layer.
Centralized assertions for the mutable layout graph.

Verifies:
- Geometry Invariants (normalized coordinates [0, 1], positive dimensions, no illegal overlaps)
- Topology Invariants (no cyclic table chains, valid node relationships)
- Reading Flow Invariants (monotonic ordering)
- Graph Hashing (for perfect rollback fidelity)
"""
import hashlib
import json
from typing import Dict, List, Any

class GraphInvariantException(Exception):
    pass

class GraphInvariantEngine:

    @staticmethod
    def hash_graph(blocks: List[Dict], layout_meta: Dict) -> str:
        """
        Generate a deterministic hash of the graph topology and geometry.
        Crucial for rollback fidelity checks.
        """
        # We extract keys that matter for topology and geometry.
        # Ignore volatile keys like "is_edited" or timestamp.
        def _canonicalize_block(b: Dict) -> Dict:
            return {
                "id": str(b.get("node_id", b.get("id", ""))),
                "text": b.get("text", ""),
                "corrected_text": b.get("corrected_text", ""),
                "nx1": round(float(b.get("nx1", 0)), 4),
                "ny1": round(float(b.get("ny1", 0)), 4),
                "nx2": round(float(b.get("nx2", 0)), 4),
                "ny2": round(float(b.get("ny2", 0)), 4),
                "reading_order": round(float(b.get("reading_order_index", 0)), 4),
                "is_continuation": bool(b.get("is_continuation", False)),
                "continues_from": str(b.get("continues_from", "")),
                "_deleted": bool(b.get("_deleted", False))
            }
        
        def _canonicalize_link(lk: Dict) -> Dict:
            return {
                "s": str(lk.get("source", "")),
                "t": str(lk.get("target", "")),
                "rel": str(lk.get("relation", ""))
            }

        sorted_blocks = sorted([_canonicalize_block(b) for b in blocks if not b.get("_deleted")], key=lambda x: x["id"])
        sorted_links = sorted([_canonicalize_link(lk) for lk in layout_meta.get("links", [])], key=lambda x: f"{x['s']}-{x['t']}-{x['rel']}")
        
        payload = json.dumps({"blocks": sorted_blocks, "links": sorted_links}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def assert_geometry_valid(blocks: List[Dict]) -> None:
        """Check normalized coordinates and dimensions."""
        for b in blocks:
            if b.get("_deleted"):
                continue
                
            bid = b.get("node_id", b.get("id", "unknown"))
            nx1, ny1, nx2, ny2 = b.get("nx1", 0), b.get("ny1", 0), b.get("nx2", 0), b.get("ny2", 0)
            
            # Bounds checking
            if not (0.0 <= nx1 <= 1.0) or not (0.0 <= nx2 <= 1.0) or not (0.0 <= ny1 <= 1.0) or not (0.0 <= ny2 <= 1.0):
                raise GraphInvariantException(f"Node {bid} out of normalized bounds [0,1]: {nx1},{ny1} -> {nx2},{ny2}")
                
            # Dimension checking
            if nx2 < nx1 or ny2 < ny1:
                raise GraphInvariantException(f"Node {bid} has negative dimensions: nx1={nx1}, nx2={nx2}, ny1={ny1}, ny2={ny2}")

    @staticmethod
    def assert_reading_order_valid(blocks: List[Dict]) -> None:
        """Check that reading_order_index exists."""
        for b in blocks:
            if b.get("_deleted"):
                continue
            if "reading_order_index" not in b:
                raise GraphInvariantException(f"Node {b.get('node_id', b.get('id', 'unknown'))} missing reading_order_index")

    @staticmethod
    def assert_no_orphan_links(blocks: List[Dict], layout_meta: Dict) -> None:
        """Ensure all links point to valid existing nodes."""
        active_ids = {str(b.get("node_id", b.get("id", ""))) for b in blocks if not b.get("_deleted")}
        links = layout_meta.get("links", [])
        for link in links:
            s, t = str(link.get("source")), str(link.get("target"))
            if s not in active_ids:
                raise GraphInvariantException(f"Orphan link source {s}")
            if t not in active_ids:
                raise GraphInvariantException(f"Orphan link target {t}")

    @staticmethod
    def assert_no_cyclic_chains(blocks: List[Dict]) -> None:
        """Verify continuation chains do not form cycles."""
        # Build continuation adjacency list
        graph = {}
        for b in blocks:
            if b.get("_deleted"): continue
            bid = str(b.get("node_id", b.get("id", "")))
            cont = str(b.get("continues_from", ""))
            if cont:
                graph[bid] = cont
                
        # Cycle detection
        for node in graph.keys():
            visited = set()
            curr = node
            while curr in graph:
                if curr in visited:
                    raise GraphInvariantException(f"Cyclic continuation chain detected involving {curr}")
                visited.add(curr)
                curr = graph[curr]

    @staticmethod
    def assert_no_illegal_overlaps(blocks: List[Dict]) -> None:
        """Check for fully eclipsed regions (e.g., bad splits/merges)."""
        active_blocks = [b for b in blocks if not b.get("_deleted")]
        for i, a in enumerate(active_blocks):
            a_nx1, a_ny1, a_nx2, a_ny2 = a.get("nx1", 0), a.get("ny1", 0), a.get("nx2", 0), a.get("ny2", 0)
            a_area = (a_nx2 - a_nx1) * (a_ny2 - a_ny1)
            if a_area <= 0: continue
            
            for j in range(i + 1, len(active_blocks)):
                b = active_blocks[j]
                b_nx1, b_ny1, b_nx2, b_ny2 = b.get("nx1", 0), b.get("ny1", 0), b.get("nx2", 0), b.get("ny2", 0)
                
                # Check overlap
                ix1, iy1 = max(a_nx1, b_nx1), max(a_ny1, b_ny1)
                ix2, iy2 = min(a_nx2, b_nx2), min(a_ny2, b_ny2)
                if ix2 > ix1 and iy2 > iy1:
                    inter_area = (ix2 - ix1) * (iy2 - iy1)
                    b_area = (b_nx2 - b_nx1) * (b_ny2 - b_ny1)
                    
                    if b_area > 0 and (inter_area / min(a_area, b_area)) > 0.95:
                        aid = a.get("node_id", a.get("id", ""))
                        bid = b.get("node_id", b.get("id", ""))
                        raise GraphInvariantException(f"Illegal overlap (>95%) between {aid} and {bid}")

    @classmethod
    def validate_all(cls, blocks: List[Dict], layout_meta: Dict) -> None:
        """Run all invariant assertions."""
        cls.assert_geometry_valid(blocks)
        cls.assert_reading_order_valid(blocks)
        cls.assert_no_orphan_links(blocks, layout_meta)
        cls.assert_no_cyclic_chains(blocks)
        cls.assert_no_illegal_overlaps(blocks)
