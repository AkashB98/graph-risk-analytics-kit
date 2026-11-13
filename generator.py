"""Deterministic synthetic transaction graph — fictional entities.

SYNTHETIC DATA ONLY. No real person, account, or transaction data is
ever used. Every node and edge is fabricated from a seeded PRNG so the
same seed always yields the same graph, byte-for-byte.

Nodes are accounts/entities; directed edges are transactions carrying
an amount and an integer timestamp ``ts`` (1..90, read as days).

Planted risk patterns (ground-truth tagged on their edges):

  * peel chain      — PEEL_00 -> ... -> PEEL_05, amounts falling 10%
                      at each hop (each hop "peels" a cut off);
  * round-trip cycle — CYCLE_A -> B -> C -> D -> A;
  * smurfing        — SMURF_SRC fans out to five intermediaries that
                      all fan in to SMURF_SINK (fan-out / fan-in);
  * layered path    — LAYER_00 -> LAYER_01 -> LAYER_02 ->
                      SANCTIONED_01 (layers hiding the destination).

Planted DECOYS (legitimate shapes that must NOT score as risk):

  * HUB_EXCHANGE — a legitimate exchange hub with 36 counterparties
    (18 send to it, it sends to 18 more) plus one direct edge to
    SANCTIONED_01. High degree alone is not risk: degree-normalised
    propagation keeps its risk score tiny.
  * PAYROLL_01 — a payroll fan-out to 12 employees whose accounts go
    nowhere else. Fan-out alone is not smurfing: there is no fan-in.

One future edge (FUTURE_01 -> SANCTIONED_01 at ts=88) exists only to
prove the as-of discipline: features at ts <= 50 must not see it.

Background activity is a DAG over the legit pool (edges only from a
lower-indexed node to a higher-indexed one), so background traffic can
never accidentally form a cycle or a peel chain.
"""

from __future__ import annotations

import json
import random
from typing import Dict, List

DEFAULT_SEED = 42
DEFAULT_LEGIT = 36
MAX_TS = 90

NODE_FIELDS = ["node_id", "archetype"]
EDGE_FIELDS = ["edge_id", "src", "dst", "amount", "ts", "planted"]

ARCHETYPES = ["legit", "sanctioned", "layered", "cycle", "peel",
              "smurf_source", "smurf_mid", "smurf_sink", "hub",
              "payroll", "employee", "future"]
PLANTED_TAGS = [None, "layered", "cycle", "peel", "smurf",
                "hub_decoy", "payroll_decoy", "future"]
BAD_ARCHETYPES = ["layered", "cycle", "peel", "smurf_source",
                  "smurf_mid", "smurf_sink"]
SANCTIONED = "SANCTIONED_01"
HUB = "HUB_EXCHANGE"


def _nodes(legit_count: int) -> List[Dict]:
    rows = [{"node_id": SANCTIONED, "archetype": "sanctioned"},
            {"node_id": HUB, "archetype": "hub"},
            {"node_id": "PAYROLL_01", "archetype": "payroll"},
            {"node_id": "FUTURE_01", "archetype": "future"}]
    for i in range(3):
        rows.append({"node_id": f"LAYER_0{i}", "archetype": "layered"})
    for name in ("A", "B", "C", "D"):
        rows.append({"node_id": f"CYCLE_{name}", "archetype": "cycle"})
    for i in range(6):
        rows.append({"node_id": f"PEEL_0{i}", "archetype": "peel"})
    rows.append({"node_id": "SMURF_SRC", "archetype": "smurf_source"})
    for i in range(1, 6):
        rows.append({"node_id": f"SMURF_M{i}", "archetype": "smurf_mid"})
    rows.append({"node_id": "SMURF_SINK", "archetype": "smurf_sink"})
    for i in range(1, 13):
        rows.append({"node_id": f"EMP_{i:02d}", "archetype": "employee"})
    for i in range(1, legit_count + 1):
        rows.append({"node_id": f"LEGIT_{i:03d}", "archetype": "legit"})
    return rows


def generate_dataset(seed: int = DEFAULT_SEED,
                     legit_count: int = DEFAULT_LEGIT) -> Dict:
    """Return the synthetic graph, deterministic for ``seed``."""
    if legit_count < 36:
        raise ValueError("legit_count must be >= 36 (hub needs 36 "
                         "counterparties)")
    rng = random.Random(seed)
    raw = []  # (src, dst, amount, ts, planted)

    def add(src, dst, amount, ts, planted):
        raw.append((src, dst, round(float(amount), 2), int(ts), planted))

    # --- layered path to the sanctioned node -------------------------
    add("LAYER_00", "LAYER_01", 4800.0, 10, "layered")
    add("LAYER_01", "LAYER_02", 4700.0, 11, "layered")
    add("LAYER_02", SANCTIONED, 4600.0, 12, "layered")

    # --- round-trip cycle --------------------------------------------
    add("CYCLE_A", "CYCLE_B", 3000.0, 20, "cycle")
    add("CYCLE_B", "CYCLE_C", 3000.0, 21, "cycle")
    add("CYCLE_C", "CYCLE_D", 3000.0, 22, "cycle")
    add("CYCLE_D", "CYCLE_A", 3000.0, 23, "cycle")

    # --- peel chain (amounts fall exactly 10% per hop) ---------------
    amount = 10000.0
    peel_nodes = [f"PEEL_0{i}" for i in range(6)]
    for i in range(5):
        add(peel_nodes[i], peel_nodes[i + 1], amount, 30 + i, "peel")
        amount = round(amount * 0.9, 2)

    # --- smurfing fan-out / fan-in -----------------------------------
    for i in range(1, 6):
        add("SMURF_SRC", f"SMURF_M{i}", 900.0, 40, "smurf")
        add(f"SMURF_M{i}", "SMURF_SINK", 880.0, 41, "smurf")

    # --- decoy: legitimate high-degree exchange hub ------------------
    legit = [f"LEGIT_{i:03d}" for i in range(1, legit_count + 1)]
    for i in range(18):
        add(legit[i], HUB, round(rng.uniform(200.0, 2500.0), 2),
            5 + i, "hub_decoy")
    for i in range(18, 36):
        add(HUB, legit[i], round(rng.uniform(200.0, 2500.0), 2),
            20 + (i - 18), "hub_decoy")
    # The sharp edge: the hub touches the sanctioned node directly.
    # Degree normalisation — not the absence of a path — is what must
    # keep the hub's propagated risk low.
    add(HUB, SANCTIONED, 750.0, 15, "hub_decoy")

    # --- decoy: payroll fan-out (no fan-in) ---------------------------
    add("LEGIT_002", "PAYROLL_01", 60000.0, 5, "payroll_decoy")
    for i in range(1, 13):
        add("PAYROLL_01", f"EMP_{i:02d}",
            round(rng.uniform(2800.0, 5200.0), 2), 45, "payroll_decoy")

    # --- future edge (as-of leakage canary) ---------------------------
    add("FUTURE_01", SANCTIONED, 5000.0, 88, "future")

    # --- background DAG over the legit pool ---------------------------
    # Targets are sampled WITHOUT replacement per source, so the
    # background never creates a duplicate (src, dst) pair.
    for i, src in enumerate(legit):
        if i + 1 >= len(legit):
            continue
        targets = rng.sample(range(i + 1, len(legit)),
                             k=min(rng.randint(1, 2), len(legit) - i - 1))
        for j in targets:
            add(src, legit[j], round(rng.uniform(20.0, 2000.0), 2),
                rng.randint(1, MAX_TS), None)

    raw.sort(key=lambda e: (e[3], e[0], e[1], e[2]))
    edges = [{"edge_id": f"E{k + 1:05d}", "src": s, "dst": d,
              "amount": a, "ts": t, "planted": p}
             for k, (s, d, a, t, p) in enumerate(raw)]
    nodes = _nodes(legit_count)
    return {"seed": seed, "max_ts": MAX_TS, "node_count": len(nodes),
            "nodes": nodes, "edges": edges}


def bad_node_ids(dataset: Dict) -> List[str]:
    return sorted(n["node_id"] for n in dataset["nodes"]
                  if n["archetype"] in BAD_ARCHETYPES)


def dataset_to_json(dataset: Dict) -> str:
    return json.dumps(dataset, sort_keys=True) + "\n"
