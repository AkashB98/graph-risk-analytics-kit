"""AS-OF feature table — the analytics-engineering hook.

An **as-of feature table** — one row per node, computed as if the
clock stopped at time ``t`` — where every feature uses ONLY edges
with ``ts <= t``. This is the point-in-time discipline analytics
engineering applies to any time-travel-sensitive feature: a feature
that quietly reads the future (**leakage** — information from after
the prediction moment slipping into the features) inflates every
offline score and collapses in production. The planted FUTURE_01
edge at ts=88 is the canary: at as-of 50 its sanctioned exposure is
exactly 0; at as-of 90 it is 0.5.
"""

from __future__ import annotations

from typing import Dict, List

from generator import SANCTIONED
from graph import (build_graph, khop_decayed_exposure,
                   label_propagation, personalized_pagerank,
                   strongly_connected_components, hops_to_seeds)


def build_feature_table(dataset: Dict, as_of: int) -> List[Dict]:
    """One feature row per node, using only edges with ts <= as_of."""
    if not isinstance(as_of, int) or isinstance(as_of, bool) \
            or not (0 <= as_of <= dataset["max_ts"]):
        raise ValueError(f"as_of must be an int in [0, {dataset['max_ts']}]")
    graph = build_graph(dataset["nodes"], dataset["edges"], as_of=as_of)
    archetype = {n["node_id"]: n["archetype"] for n in dataset["nodes"]}

    sccs = strongly_connected_components(graph)
    scc_of = {}
    for comp in sccs:
        for member in comp:
            scc_of[member] = comp
    exposure = khop_decayed_exposure(graph, [SANCTIONED])
    rev_pagerank = personalized_pagerank(graph.reversed(), [SANCTIONED])
    labels = label_propagation(graph)
    hops = hops_to_seeds(graph, [SANCTIONED])

    in_amount = {n: 0.0 for n in graph.nodes}
    out_amount = {n: 0.0 for n in graph.nodes}
    for e in graph.edges:
        out_amount[e["src"]] += e["amount"]
        in_amount[e["dst"]] += e["amount"]

    rows = []
    for node in graph.nodes:
        comp = scc_of[node]
        rows.append({
            "node_id": node,
            "archetype": archetype[node],
            "as_of": as_of,
            "in_degree": graph.in_degree(node),
            "out_degree": graph.out_degree(node),
            "in_amount": round(in_amount[node], 2),
            "out_amount": round(out_amount[node], 2),
            "scc_size": len(comp),
            "scc_members": comp,
            "in_cycle": len(comp) > 1,
            "khop_exposure": exposure[node],
            "pagerank_to_sanctioned": rev_pagerank[node],
            "community": labels[node],
            "hops_to_sanctioned": hops[node],
        })
    return rows
