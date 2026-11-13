"""Golden evals for graph-risk-analytics-kit.

SYNTHETIC DATA ONLY (fictional entities). Every eval is
deterministic: run_evals.py writes eval_report.json and the file
must be byte-identical across runs. No timestamps, ports, or temp
paths enter the report — only names, booleans, pinned counts and
values.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import (EXIT_ERROR, EXIT_OK, load_dataset,  # noqa: E402
                 main as cli_main, make_server, reset_state)
from features import build_feature_table  # noqa: E402
from generator import HUB, bad_node_ids, dataset_to_json, generate_dataset  # noqa: E402
from graph import (Graph, khop_decayed_exposure,  # noqa: E402
                   strongly_connected_components)
from report import build_markdown_report  # noqa: E402
from scoring import planted_recall, score_graph  # noqa: E402
from validation import validate_dataset  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURE = os.path.join(ROOT, "fixtures", "sample_graph.json")
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return passed


def _run_cli(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


def _by(rows):
    return {r["node_id"]: r for r in rows}


def main():
    print("== golden evals: graph-risk-analytics-kit ==")
    data = generate_dataset()
    result = score_graph(data)
    rows = _by(result["rows"])

    # E1: generator determinism (bytes pinned)
    text1 = dataset_to_json(generate_dataset())
    text2 = dataset_to_json(generate_dataset())
    md5 = hashlib.md5(text1.encode()).hexdigest()
    check("E1 generator determinism (seed=42)",
          text1 == text2 and md5 == "01605c3e91ea264ce79abfbc0332cb9a",
          f"dataset_md5={md5}")

    # E2: headline counts pinned.
    check("E2 headline counts (72 nodes, 123 edges, 20 planted bad)",
          data["node_count"] == 72 and len(data["edges"]) == 123
          and len(bad_node_ids(data)) == 20
          and validate_dataset(data) == [],
          f"nodes={data['node_count']} edges={len(data['edges'])}")

    # E3: planted-pattern recall pinned at 20/20.
    rec = planted_recall(data)
    check("E3 planted-pattern recall 20/20 = 1.0",
          (rec["planted_bad"], rec["caught"], rec["recall"], rec["missed"])
          == (20, 20, 1.0, []),
          f"recall={rec['recall']}")

    # E4: decoy proof — the hub's propagated risk stays below every
    # planted bad pattern despite 37 counterparties and a direct
    # edge to the sanctioned node; payroll carries no flag either.
    bad_min = min(rows[n]["risk_score"] for n in bad_node_ids(data))
    check("E4 decoys quiet (hub 0.026316 < planted min 0.125; payroll 0.0)",
          rows[HUB]["risk_score"] == 0.026316 and rows[HUB]["flags"] == []
          and rows["PAYROLL_01"]["risk_score"] == 0.0
          and rows["PAYROLL_01"]["flags"] == [] and bad_min == 0.125,
          f"hub={rows[HUB]['risk_score']} bad_min={bad_min}")

    # E5: per-pattern risk scores pinned.
    check("E5 pattern scores (cycle .45, peel .45, smurf .40, "
          "layered .5/.25/.125)",
          rows["CYCLE_A"]["risk_score"] == 0.45
          and rows["PEEL_00"]["risk_score"] == 0.45
          and rows["SMURF_SRC"]["risk_score"] == 0.4
          and (rows["LAYER_02"]["risk_score"],
               rows["LAYER_01"]["risk_score"],
               rows["LAYER_00"]["risk_score"]) == (0.5, 0.25, 0.125),
          f"layered={rows['LAYER_02']['risk_score']}/"
          f"{rows['LAYER_01']['risk_score']}/{rows['LAYER_00']['risk_score']}")

    # E6: provenance pinned for every pattern family.
    cyc = rows["CYCLE_A"]["flags"][0]["provenance"]
    peel = rows["PEEL_00"]["flags"][0]["provenance"]
    smurf = rows["SMURF_M1"]["flags"][0]["provenance"]
    layered = rows["LAYER_00"]["flags"][0]["provenance"]
    check("E6 provenance (cycle path, peel amounts, smurf mids, "
          "layered path)",
          cyc["cycle_path"] == ["CYCLE_A", "CYCLE_B", "CYCLE_C",
                                "CYCLE_D", "CYCLE_A"]
          and peel["amounts"] == [10000.0, 9000.0, 8100.0, 7290.0, 6561.0]
          and len(smurf["intermediaries"]) == 5
          and smurf["role"] == "intermediary"
          and layered["path_to_sanctioned"] == ["LAYER_00", "LAYER_01",
                                                "LAYER_02", "SANCTIONED_01"],
          f"peel_path={peel['path']}")

    # E7: as-of leakage canary — the ts=88 future edge is invisible
    # at as-of 50 and fully visible at as-of 90.
    early = _by(build_feature_table(data, as_of=50))
    check("E7 as-of leakage canary (FUTURE_01: 0.0 @50 -> 0.5 @90)",
          early["FUTURE_01"]["khop_exposure"] == 0.0
          and early["FUTURE_01"]["out_degree"] == 0
          and rows["FUTURE_01"]["khop_exposure"] == 0.5,
          f"@50={early['FUTURE_01']['khop_exposure']} "
          f"@90={rows['FUTURE_01']['khop_exposure']}")

    # E8: Tarjan — exactly one multi-node SCC in the seeded graph,
    # and a 5,000-node chain resolves iteratively (no recursion).
    graph = Graph([n["node_id"] for n in data["nodes"]], data["edges"])
    multi = [c for c in strongly_connected_components(graph) if len(c) > 1]
    n = 5000
    ids = [f"N{i:05d}" for i in range(n)]
    chain = Graph(ids, [{"src": ids[i], "dst": ids[i + 1], "amount": 1.0,
                         "ts": 1, "planted": None} for i in range(n - 1)])
    check("E8 Tarjan SCC (one cycle component; 5000-chain iterative)",
          multi == [["CYCLE_A", "CYCLE_B", "CYCLE_C", "CYCLE_D"]]
          and len(strongly_connected_components(chain)) == n,
          f"multi_sccs={multi}")

    # E9: personalized PageRank pinned (reversed graph, sanctioned seed).
    check("E9 pagerank pinned (sanctioned 0.38346, hub 0.108647)",
          rows["SANCTIONED_01"]["pagerank_to_sanctioned"] == 0.38346
          and rows[HUB]["pagerank_to_sanctioned"] == 0.108647
          and abs(sum(r["pagerank_to_sanctioned"]
                      for r in result["rows"]) - 1.0) < 0.001,
          f"sanctioned_pr={rows['SANCTIONED_01']['pagerank_to_sanctioned']}")

    # E10: degree normalisation on a hand-built hub (exact values).
    pairs = [("HUB", f"L{i}") for i in range(9)] + [("HUB", "S"), ("X", "S")]
    hand = Graph(["HUB", "S", "X"] + [f"L{i}" for i in range(9)],
                 [{"src": s, "dst": d, "amount": 1.0, "ts": 1,
                   "planted": None} for s, d in pairs])
    exp = khop_decayed_exposure(hand, ["S"])
    check("E10 k-hop normalisation hand case (hub 0.05 vs direct 0.5)",
          exp["HUB"] == 0.05 and exp["X"] == 0.5,
          f"hub={exp['HUB']} direct={exp['X']}")

    # E11: CLI check exit codes 0 / 2.
    import tempfile
    tmp = tempfile.mkdtemp(prefix="graph-risk-evals-")
    good_path = os.path.join(tmp, "graph.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    codes = (_run_cli(["check", "--input", good_path]),
             _run_cli(["check", "--input", "/tmp/no-such-graph-xyz.json"]))
    check("E11 CLI check exit codes 0/2 (seeded passes)",
          codes == (EXIT_OK, EXIT_ERROR), f"codes={codes}")

    # E12: serve round-trip matches local score + report.
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                    timeout=10) as resp:
            health = json.loads(resp.read())
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/score", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/report",
                                    timeout=10) as resp:
            served_report = resp.read().decode()
        serve_ok = health == {"status": "ok"} \
            and served["flagged_count"] == result["flagged_count"] \
            and served_report == build_markdown_report(data)
    finally:
        server.shutdown()
        server.server_close()
        reset_state()
    check("E12 serve round-trip matches local score + report", serve_ok)

    # E13: bundled fixture pinned (the seeded graph itself).
    fixture = load_dataset(FIXTURE)
    check("E13 fixture pinned (72 nodes, 123 edges, clean)",
          fixture == generate_dataset()
          and len(fixture["edges"]) == 123
          and validate_dataset(fixture) == [],
          f"fixture_edges={len(fixture['edges'])}")

    # E14: report determinism + the required honesty line.
    md1 = build_markdown_report(data)
    md2 = build_markdown_report(generate_dataset())
    check("E14 report determinism + honesty line",
          md1 == md2 and "NOT compliance-grade" in md1
          and "0.026316" in md1 and "Caught 20 of 20" in md1,
          f"report_md5={hashlib.md5(md1.encode()).hexdigest()}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total_count = len(RESULTS)
    summary_doc = {"passed": passed, "total": total_count,
                   "all_passed": passed == total_count, "evals": RESULTS}
    with open(os.path.join(HERE, "eval_report.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_doc, sort_keys=True) + "\n")
    print(f"\n{passed}/{total_count} evals passed -> evals/eval_report.json")
    return 0 if passed == total_count else 1


if __name__ == "__main__":
    sys.exit(main())
