"""Shared builders for the test suite (not a test module)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_dataset(node_archetypes, edge_rows, max_ts=90):
    """node_archetypes: {node_id: archetype};
    edge_rows: [(src, dst, amount, ts, planted)]."""
    nodes = [{"node_id": n, "archetype": a}
             for n, a in sorted(node_archetypes.items())]
    edges = [{"edge_id": f"E{k + 1:05d}", "src": s, "dst": d,
              "amount": float(a), "ts": t, "planted": p}
             for k, (s, d, a, t, p) in enumerate(edge_rows)]
    return {"seed": 0, "max_ts": max_ts, "node_count": len(nodes),
            "nodes": nodes, "edges": edges}


def graph_of(node_ids, pairs):
    from graph import Graph
    edges = [{"src": s, "dst": d, "amount": 1.0, "ts": 1,
              "planted": None} for s, d in pairs]
    return Graph(list(node_ids), edges)
