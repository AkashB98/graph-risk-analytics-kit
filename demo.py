"""End-to-end demo: generate -> validate -> features (as-of) ->
score (patterns + decoys) -> as-of leakage canary -> report ->
check -> serve.

SYNTHETIC DATA ONLY (fictional entities). Runs fully offline; the
serve round-trip is loopback-only on an ephemeral port.
Every stage asserts.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import EXIT_OK, main as cli_main, make_server, reset_state  # noqa: E402
from generator import HUB, bad_node_ids, dataset_to_json, generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from scoring import planted_recall, score_graph  # noqa: E402
from validation import validate_dataset  # noqa: E402


def _request(port: int, path: str, payload=None, method: str = "GET"):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read()


def main() -> None:
    print("== 1. generate synthetic graph (seed=42) ==")
    data = generate_dataset()
    assert data == generate_dataset(), "generator must be deterministic"
    assert validate_dataset(data) == [], validate_dataset(data)[:3]
    print(f"   {data['node_count']} nodes, {len(data['edges'])} edges, "
          f"{len(bad_node_ids(data))} planted bad nodes, "
          "deterministic re-generation verified")

    print("\n== 2. score: planted patterns caught, decoys quiet ==")
    result = score_graph(data)
    by_node = {r["node_id"]: r for r in result["rows"]}
    recall = planted_recall(data)
    print(f"   planted recall: {recall['caught']}/{recall['planted_bad']} "
          f"= {recall['recall']}")
    assert recall["recall"] == 1.0, recall
    for decoy in (HUB, "PAYROLL_01"):
        print(f"   decoy {decoy}: risk={by_node[decoy]['risk_score']} "
              f"flags={len(by_node[decoy]['flags'])}")
        assert not by_node[decoy]["flags"]
    bad_min = min(by_node[n]["risk_score"] for n in bad_node_ids(data))
    print(f"   hub risk {by_node[HUB]['risk_score']} < lowest planted "
          f"bad score {bad_min} (degree normalisation, not luck)")
    assert by_node[HUB]["risk_score"] < bad_min
    for node in ("LAYER_02", "CYCLE_A", "PEEL_00", "SMURF_SRC"):
        pats = [f["pattern"] for f in by_node[node]["flags"]]
        print(f"   {node}: risk={by_node[node]['risk_score']} flags={pats}")

    print("\n== 3. as-of leakage canary (FUTURE_01 edge lands at ts=88) ==")
    early = {r["node_id"]: r for r in score_graph(data, as_of=50)["rows"]}
    print(f"   as_of=50: FUTURE_01 exposure="
          f"{early['FUTURE_01']['khop_exposure']} flags="
          f"{len(early['FUTURE_01']['flags'])}")
    print(f"   as_of=90: FUTURE_01 exposure="
          f"{by_node['FUTURE_01']['khop_exposure']}")
    assert early["FUTURE_01"]["khop_exposure"] == 0.0
    assert by_node["FUTURE_01"]["khop_exposure"] == 0.5

    print("\n== 4. markdown report ==")
    md = build_markdown_report(data)
    assert md == build_markdown_report(generate_dataset())
    assert "NOT compliance-grade" in md and "HUB_EXCHANGE" in md
    print("   " + md.splitlines()[2][:110])

    print("\n== 5. CLI check gate ==")
    import tempfile
    tmp = tempfile.mkdtemp(prefix="graph-risk-demo-")
    good_path = os.path.join(tmp, "graph.json")
    with open(good_path, "w", encoding="utf-8") as fh:
        fh.write(dataset_to_json(data))
    code_ok = cli_main(["check", "--input", good_path])
    code_err = cli_main(["check", "--input", "/tmp/no-such-graph-xyz.json"])
    print(f"   seeded={code_ok} missing-file={code_err}")
    assert code_ok == EXIT_OK and code_err == 2

    print("\n== 6. live localhost serve round-trip ==")
    reset_state(data)
    server = make_server(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _request(port, "/health")
        assert status == 200 and json.loads(body) == {"status": "ok"}
        status, body = _request(port, "/score", payload={}, method="POST")
        served = json.loads(body)
        assert status == 200 and served["flagged_count"] == result["flagged_count"]
        status, body = _request(port, "/report")
        assert status == 200 and body.decode() == md
        print("   POST /score matches local scoring; GET /report matches "
              "the local report")
    finally:
        server.shutdown()
        server.server_close()
        reset_state()

    print("\nDemo OK: generate, score, decoys, as-of canary, report, "
          "check and serve verified.")


if __name__ == "__main__":
    main()
