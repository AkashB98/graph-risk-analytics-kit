"""Data-quality gate for the synthetic transaction graph.

Reports issues, never raises on bad data, so the CLI ``check`` gate
maps data problems to exit code 2, distinctly from a quality breach
(exit 1).
"""

from __future__ import annotations

from typing import Dict, List

from generator import ARCHETYPES, EDGE_FIELDS, NODE_FIELDS, PLANTED_TAGS


def validate_dataset(dataset: Dict) -> List[str]:
    issues: List[str] = []
    if not isinstance(dataset, dict):
        return ["dataset must be a JSON object"]
    max_ts = dataset.get("max_ts")
    if not isinstance(max_ts, int) or isinstance(max_ts, bool) or max_ts < 1:
        return [f"dataset.max_ts missing or invalid: {max_ts!r}"]
    nodes = dataset.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return ["dataset.nodes missing or empty"]
    edges = dataset.get("edges")
    if not isinstance(edges, list) or not edges:
        return ["dataset.edges missing or empty"]
    known = set()
    for row in nodes:
        if not isinstance(row, dict):
            issues.append("node row is not an object")
            continue
        for field in NODE_FIELDS:
            if field not in row:
                issues.append(f"missing field {field} in node {row!r:.60}")
        if row.get("archetype") not in ARCHETYPES:
            issues.append(f"bad archetype: {row.get('archetype')!r}")
        nid = row.get("node_id")
        if nid in known:
            issues.append(f"duplicate node_id: {nid}")
        known.add(nid)
    seen = set()
    for row in edges:
        if not isinstance(row, dict):
            issues.append("edge row is not an object")
            continue
        for field in EDGE_FIELDS:
            if field not in row:
                issues.append(f"missing field {field} in edge {row!r:.60}")
        eid = row.get("edge_id")
        if eid in seen:
            issues.append(f"duplicate edge_id: {eid}")
        seen.add(eid)
        if row.get("src") not in known:
            issues.append(f"unknown src: {row.get('src')!r}")
        if row.get("dst") not in known:
            issues.append(f"unknown dst: {row.get('dst')!r}")
        if row.get("src") == row.get("dst"):
            issues.append(f"self-loop edge: {eid}")
        ts = row.get("ts")
        if not isinstance(ts, int) or isinstance(ts, bool) \
                or not (0 <= ts <= max_ts):
            issues.append(f"bad ts for {eid}: {ts!r}")
        amt = row.get("amount")
        if not isinstance(amt, (int, float)) or isinstance(amt, bool) \
                or amt <= 0:
            issues.append(f"bad amount for {eid}: {amt!r}")
        if row.get("planted") not in PLANTED_TAGS:
            issues.append(f"bad planted tag for {eid}: {row.get('planted')!r}")
    return issues
