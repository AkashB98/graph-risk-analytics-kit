"""Pattern detectors + risk flags, every flag carrying provenance.

A **flag** — an account marked for review — is only useful if an
analyst can see WHY. Every flag here carries a ``provenance`` object:
the pattern that produced it and the concrete evidence (the cycle's
members, the peel chain's path and amounts, the smurfing source /
intermediaries / sink, or the path to the sanctioned node). No flag
is a bare score.

This module deliberately does NO alert-threshold tuning — tuning
monitoring thresholds is a different problem (and a sibling repo's
job). Detectors here are structural: a cycle either closes or it
does not; a chain either peels monotonically or it does not.
"""

from __future__ import annotations

from typing import Dict, List

from features import build_feature_table
from generator import SANCTIONED
from graph import build_graph, path_to_seed, strongly_connected_components

EXPOSURE_FLAG_FLOOR = 0.05
CYCLE_POINTS = 0.45
PEEL_POINTS = 0.45
SMURF_POINTS = 0.40


def detect_peel_chains(graph) -> List[Dict]:
    """Maximal chains of single-in/single-out nodes whose amounts
    fall strictly at every hop, at least 4 edges long."""
    amounts = {}
    for e in graph.edges:
        amounts[(e["src"], e["dst"])] = e["amount"]
    chains = []
    visited_edges = set()
    heads = [n for n in graph.nodes
             if graph.out_degree(n) == 1 and graph.in_degree(n) == 0]
    for head in sorted(heads):
        path = [head]
        edge_amounts = []
        node = head
        while graph.out_degree(node) == 1:
            nxt = graph.succ[node][0]
            if nxt in path:
                break
            edge_amounts.append(amounts[(node, nxt)])
            visited_edges.add((node, nxt))
            path.append(nxt)
            node = nxt
            if not (graph.in_degree(node) == 1
                    and graph.out_degree(node) <= 1):
                break
        if len(edge_amounts) >= 4 and min(edge_amounts) >= 5000.0 and all(
                edge_amounts[i + 1] < edge_amounts[i]
                for i in range(len(edge_amounts) - 1)):
            chains.append({"path": path, "amounts": edge_amounts})
    return chains


def detect_smurfing(graph) -> List[Dict]:
    """Fan-out / fan-in convergence: a source reaching one sink via
    >= 4 distinct single-step intermediaries. Fan-out alone (payroll)
    never matches — its targets share no common successor."""
    findings = []
    for src in graph.nodes:
        mids = graph.succ[src]
        if len(mids) < 4:
            continue
        by_sink: Dict[str, List[str]] = {}
        for mid in mids:
            # A smurfing intermediary is a pure pass-through: exactly
            # one way in, exactly one way out. Hub counterparties and
            # payroll employees fail this on purpose.
            if graph.in_degree(mid) != 1 or graph.out_degree(mid) != 1:
                continue
            for sink in graph.succ[mid]:
                if sink != src:
                    by_sink.setdefault(sink, []).append(mid)
        for sink in sorted(by_sink):
            intermediaries = sorted(set(by_sink[sink]))
            if len(intermediaries) >= 4:
                findings.append({"source": src, "sink": sink,
                                 "intermediaries": intermediaries})
    return findings


def score_graph(dataset: Dict, as_of=None) -> Dict:
    """Feature table + flags + risk scores as of ``as_of`` (default:
    the dataset's max timestamp)."""
    if as_of is None:
        as_of = dataset["max_ts"]
    features = build_feature_table(dataset, as_of)
    graph = build_graph(dataset["nodes"], dataset["edges"], as_of=as_of)
    by_node = {row["node_id"]: row for row in features}

    points: Dict[str, float] = {n: 0.0 for n in graph.nodes}
    flags: Dict[str, List[Dict]] = {n: [] for n in graph.nodes}

    def add_flag(node, pattern, pts, provenance):
        flags[node].append({"pattern": pattern, "provenance": provenance})
        points[node] += pts

    # --- round-trip cycles (SCCs with > 1 member) ---------------------
    for comp in strongly_connected_components(graph):
        if len(comp) <= 1:
            continue
        start = comp[0]
        ring = [start]
        node = start
        for _ in range(len(comp)):
            nxt = [s for s in graph.succ[node] if s in comp and s not in ring]
            if not nxt:
                break
            node = nxt[0]
            ring.append(node)
        cycle_path = ring + [start]
        for member in comp:
            add_flag(member, "round_trip_cycle", CYCLE_POINTS,
                     {"scc": comp, "cycle_path": cycle_path})

    # --- peel chains ---------------------------------------------------
    for chain in detect_peel_chains(graph):
        for member in chain["path"]:
            add_flag(member, "peel_chain", PEEL_POINTS,
                     {"path": chain["path"], "amounts": chain["amounts"]})

    # --- smurfing fan-out / fan-in -------------------------------------
    for finding in detect_smurfing(graph):
        prov = {"source": finding["source"], "sink": finding["sink"],
                "intermediaries": finding["intermediaries"]}
        add_flag(finding["source"], "smurfing_fan_out_in",
                 SMURF_POINTS, dict(prov, role="source"))
        for mid in finding["intermediaries"]:
            add_flag(mid, "smurfing_fan_out_in",
                     SMURF_POINTS, dict(prov, role="intermediary"))
        add_flag(finding["sink"], "smurfing_fan_out_in",
                 SMURF_POINTS, dict(prov, role="sink"))

    # --- sanctioned exposure (path from the flagged node to the seed) --
    for node in graph.nodes:
        exposure = by_node[node]["khop_exposure"]
        if node == SANCTIONED or exposure < EXPOSURE_FLAG_FLOOR:
            continue
        path = path_to_seed(graph, node, [SANCTIONED])
        if path:
            add_flag(node, "sanctioned_exposure", 0.0,
                     {"path_to_sanctioned": path,
                      "hops": len(path) - 1, "khop_exposure": exposure})

    scored = []
    for row in features:
        node = row["node_id"]
        risk = round(min(1.0, points[node] + row["khop_exposure"]), 6) \
            if node != SANCTIONED else 0.0
        scored.append({**row, "risk_score": risk, "flags": flags[node]})
    flagged = [r for r in scored if r["flags"]]
    return {"as_of": as_of, "node_count": len(scored),
            "flagged_count": len(flagged), "rows": scored}


def planted_recall(dataset: Dict, as_of=None) -> Dict:
    """Share of planted bad nodes carrying at least one flag."""
    from generator import bad_node_ids
    result = score_graph(dataset, as_of=as_of)
    flagged_ids = {r["node_id"] for r in result["rows"] if r["flags"]}
    bad = bad_node_ids(dataset)
    caught = [n for n in bad if n in flagged_ids]
    return {"planted_bad": len(bad), "caught": len(caught),
            "missed": [n for n in bad if n not in flagged_ids],
            "recall": round(len(caught) / len(bad), 4) if bad else 0.0}
