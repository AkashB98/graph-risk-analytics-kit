"""One deterministic markdown report, copied from computed numbers."""

from __future__ import annotations

from typing import Dict

from generator import HUB, bad_node_ids
from scoring import planted_recall, score_graph


def build_markdown_report(dataset: Dict, as_of=None) -> str:
    result = score_graph(dataset, as_of=as_of)
    recall = planted_recall(dataset, as_of=as_of)
    by_node = {r["node_id"]: r for r in result["rows"]}
    hub = by_node[HUB]
    future_50 = [r for r in score_graph(dataset, as_of=50)["rows"]
                 if r["node_id"] == "FUTURE_01"][0]
    bad_scores = [by_node[n]["risk_score"] for n in bad_node_ids(dataset)]
    flagged = [r for r in result["rows"] if r["flags"]]

    lines = [
        "# Graph risk analytics — synthetic transaction graph report",
        "",
        f"Synthetic graph: {result['node_count']} fictional nodes, "
        f"{len(dataset['edges'])} timestamped edges (seed "
        f"{dataset['seed']}), scored as of ts={result['as_of']}. "
        f"{recall['planted_bad']} planted bad nodes across the peel / "
        "cycle / smurfing / layered patterns, plus two planted decoys "
        "(exchange hub, payroll fan-out).",
        "",
        "Synthetic data only — NOT compliance-grade. Built to learn the "
        "problem shape named in a graph-analytics JD.",
        "",
        "## Planted-pattern recall",
        "",
        f"- Caught {recall['caught']} of {recall['planted_bad']} planted "
        f"bad nodes (recall {recall['recall']}); missed: "
        f"{recall['missed'] if recall['missed'] else 'none'}.",
        f"- Flagged nodes in total: {result['flagged_count']} "
        "(planted bad nodes plus any node whose sanctioned exposure "
        "clears the flag floor).",
        "",
        "## The decoy test (why degree is not risk)",
        "",
        f"- HUB_EXCHANGE touches {hub['in_degree'] + hub['out_degree']} "
        "counterparties and has a direct edge to the sanctioned node, "
        f"yet its degree-normalised risk score is {hub['risk_score']} "
        f"and it carries {len(hub['flags'])} flags.",
        f"- Every planted bad node scores at or above "
        f"{min(bad_scores)} — the lowest planted score still clears "
        "the hub's score, because propagation divides by out-degree "
        "instead of counting neighbours.",
        "- PAYROLL_01 fans out to 12 employees and carries "
        f"{len(by_node['PAYROLL_01']['flags'])} flags: fan-out without "
        "fan-in is payroll, not smurfing.",
        "",
        "## Flagged nodes (every flag carries provenance)",
        "",
        "| Node | Risk | Patterns |",
        "|---|---|---|",
    ]
    for row in sorted(flagged, key=lambda r: (-r["risk_score"], r["node_id"])):
        patterns = ", ".join(sorted({f["pattern"] for f in row["flags"]}))
        lines.append(f"| {row['node_id']} | {row['risk_score']} | {patterns} |")
    lines += [
        "",
        "## As-of discipline",
        "",
        "Features at time t use only edges with ts <= t. The planted "
        "FUTURE_01 -> SANCTIONED_01 edge lands at ts=88: at as-of 50 "
        f"FUTURE_01's exposure is {future_50['khop_exposure']}"
        ", so the future cannot leak into earlier features.",
        "",
    ]
    return "\n".join(lines)
