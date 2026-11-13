# graph-risk-analytics-kit

**The TRM Labs Senior Data Engineer, Graph Analytics JD (surfaced 2026-11-13) asks for large-scale graph data work behind an intelligence platform: modelling how value moves between entities, and finding the structures — cycles, layering, fan-out/fan-in — that single-transaction rules cannot see. This repo is that problem, made runnable: a seeded synthetic transaction graph, five hand-implemented graph algorithms, four planted risk patterns, two planted decoys designed to break naive scoring, and an as-of feature table that cannot read the future.**

> **Honesty line: this project is synthetic and NOT compliance-grade. Built to learn the problem shape named in a Data Engineer JD — it does not represent blockchain-intelligence, AML, or graph-analytics employment experience, and no real transaction data is used anywhere in it.**

A **transaction graph** — accounts as **nodes** (dots), transactions as directed **edges** (arrows from sender to receiver, each carrying an amount and a timestamp) — exposes behaviour that per-transaction rules miss: money that leaves and comes back, money peeled hop by hop, money split into pieces and recombined, money walked through layers toward a sanctioned destination. This kit builds the whole loop on a seeded synthetic graph: plant the patterns, implement the algorithms properly, score every node, and prove — with golden evals, not adjectives — that the legitimate look-alikes do not get flagged.

Stdlib-only Python. Zero network, zero API keys, zero external dependencies.

## What this kit deliberately does not do

**No alert-threshold tuning.** Deciding where a monitoring rule's threshold sits, what an alert queue costs, and when a rule should be retired is a different problem — it is the sibling repo **transaction-monitoring-rule-tuning-kit**'s whole job. Detectors here are structural: a cycle either closes or it does not; a chain either peels monotonically or it does not; exposure is a computed quantity, not a tuned knob.

## Quickstart

```bash
# 1. Generate the synthetic graph (72 nodes x 123 edges, seed 42)
python3 cli.py generate --out graph.json

# 2. As-of feature table (features at ts=50 use only edges with ts <= 50)
python3 cli.py features --input graph.json --as-of 50

# 3. Risk flags + scores, every flag carrying its provenance
python3 cli.py score --input graph.json

# 4. The markdown report (recall, the decoy test, flagged nodes)
python3 cli.py report --input graph.json

# 5. CI gate: exit 0 = pass, 1 = quality breach (recall below 1.0, a
#    decoy scoring at/above a planted pattern, or as-of leakage),
#    2 = data-quality / IO error. Seeded data exits 0.
python3 cli.py check --input graph.json

# 6. One-command end-to-end demo (incl. a live serve round-trip)
python3 demo.py

# 7. Tiny localhost API: POST /score, POST /features, POST /report,
#    GET /report, GET /health
python3 cli.py serve --port 8765
```

## The seeded graph at a glance (seed 42)

**72 fictional nodes, 123 timestamped edges, 20 planted bad nodes** across four patterns, plus two planted decoys planted specifically to break naive graph scoring:

| Pattern | Nodes | Planted behaviour |
|---|---|---|
| peel chain | PEEL_00…PEEL_05 | a chain passing 10,000 → 9,000 → 8,100 → 7,290 → 6,561 (each hop **peels** — shaves a cut off the amount as it moves) |
| round-trip cycle | CYCLE_A…D | A → B → C → D → A: money that returns to its start |
| smurfing | SMURF_SRC, SMURF_M1…M5, SMURF_SINK | **smurfing** — splitting value into small pieces to stay unremarkable — as fan-out to 5 pass-through intermediaries that all fan in to one sink |
| layered path | LAYER_00…02 → SANCTIONED_01 | **layering** — walking value through intermediate accounts to obscure its destination — ending at the sanctioned node |
| **DECOY: exchange hub** | HUB_EXCHANGE | 18 accounts send to it, it sends to 18 more, **and it has a direct edge to SANCTIONED_01** — high degree *and* a path to the bad node |
| **DECOY: payroll** | PAYROLL_01 → EMP_01…12 | a fan-out to 12 employees who go nowhere else — fan-out with no fan-in |

Background traffic is a DAG over 36 legit accounts (edges only ever point from a lower-indexed account to a higher-indexed one), so background activity can never accidentally form a cycle, a chain, or a second path shape the evals would have to excuse.

## The algorithms (all hand-implemented, all deterministic)

- **Strongly connected components** — sets of nodes that can all reach each other by following directed edges. Computed with **Tarjan's algorithm** — a single depth-first pass that groups mutually reachable nodes — written **iteratively** (an explicit work stack instead of recursion), so a 5,000-node chain cannot crash into Python's recursion limit; eval E8 pins exactly that. A component larger than one node *is* a directed cycle.
- **k-hop decayed exposure** — how much seed risk reaches a node within k hops, worth less (**decayed** — multiplied by 0.5) at each hop, and **degree-normalised**: a node's exposure is the *average* over its successors, not the sum. That division is the whole decoy defence (below).
- **Personalized PageRank** — a **random-walk score** (imagine a walker following edges who occasionally teleports back to the seed set; nodes the walker visits often score high), **personalised** — the teleport always lands on the sanctioned node — computed by **power iteration** — repeating the update until it stops changing — on the *reversed* graph, so it scores how strongly a node feeds the sanctioned destination.
- **Flagged-path BFS** — **breadth-first search** (exploring level by level, so the first path found is the shortest) that returns actual paths, but *only* outward from a flagged set. There is deliberately **no arbitrary pair path-query API**: every path this kit emits is **provenance** — the evidence attached to a flag, e.g. `LAYER_00 → LAYER_01 → LAYER_02 → SANCTIONED_01` — never an open-ended graph query.
- **Label propagation** — a community detector where each node repeatedly adopts the most common label among its neighbours. Updates run **asynchronously in sorted node order** with sorted tie-breaking (see the development loop for why synchronous updates fail); the result is deterministic.

## The decoy test (why degree is not risk)

A naive graph scorer floods risk out of high-degree nodes: the hub touches 37 counterparties, so anything summed over neighbours makes the hub — and everyone near it — look dangerous. Degree normalisation inverts that: the hub's exposure is its successors' risk *divided by its out-degree of 19*.

| Node | Hops to sanctioned | Risk score | Flags |
|---|---|---|---|
| LAYER_02 | 1 (sole successor is the seed) | **0.5** | sanctioned_exposure |
| LAYER_01 | 2 | **0.25** | sanctioned_exposure |
| LAYER_00 | 3 | **0.125** | sanctioned_exposure |
| CYCLE_* / PEEL_* | — | **0.45** | round_trip_cycle / peel_chain |
| SMURF_* | — | **0.40** | smurfing_fan_out_in |
| **HUB_EXCHANGE** | **1 (direct edge)** | **0.026316** | **none** |
| PAYROLL_01 | — | **0.0** | **none** |

The hub is *one hop* from the sanctioned node and still scores 4.7× below the weakest planted pattern (0.125), because 0.5 ÷ 19 is small. The payroll fan-out scores zero because smurfing detection requires **convergence** — intermediaries that are pure pass-throughs (one way in, one way out) *and* share a common sink; employees share no sink. Eval E4 pins both numbers so the defence cannot quietly regress. Planted-pattern recall is **20/20 = 1.0** (eval E3), and the full flag list is 21 nodes — the 20 planted bad nodes plus FUTURE_01, whose edge is legitimately live by the final timestamp.

## As-of features: the future must not leak

An **as-of feature table** — one row of features per node, computed as if the clock stopped at time *t* — where features at *t* use **only** edges with timestamp ≤ *t*. Reading later edges into earlier features is **leakage** — information from after the moment of prediction slipping into the features — and it inflates every offline score while collapsing in production. The graph plants its own canary: `FUTURE_01 → SANCTIONED_01` lands at ts=88.

- as-of 50: FUTURE_01 exposure **0.0**, out-degree 0, no path to the sanctioned node, no flag
- as-of 90: FUTURE_01 exposure **0.5**, flagged with its one-hop provenance path

Eval E7 pins both sides, and the `check` gate fails (exit 1) if the canary ever becomes visible early.

## Why stdlib, not networkx / Neo4j

Deliberate, and worth defending in an interview: **auditability and determinism.** Every algorithm here is ~a page of readable code whose tie-breaking, iteration order, and rounding are pinned by tests; there is no library version, query-planner, or storage engine between the reader and the result, and the eval report is byte-identical across runs. The trade is real — this design is single-machine and in-memory (see limits) — but the *discipline* is the portable part: the as-of rule, provenance-on-every-flag, and degree-normalised propagation carry over unchanged to a networkx prototype or a Neo4j production graph, where they are exactly the properties that get lost first.

## Architecture

| Module | Job |
|---|---|
| `generator.py` | Deterministic synthetic graph: 72 fictional nodes, 123 edges, four planted patterns + two planted decoys + the future-edge canary; ground-truth tags on planted edges |
| `graph.py` | The five algorithms: iterative Tarjan SCC, degree-normalised k-hop decayed exposure, personalized PageRank (power iteration), flagged-path BFS, deterministic label propagation |
| `features.py` | The as-of feature table (degrees, amounts, SCC, exposure, PageRank, community, hops-to-sanctioned) using only edges with ts ≤ t |
| `scoring.py` | Structural detectors (cycle / peel / smurfing / sanctioned exposure), risk scores, provenance on every flag, planted recall |
| `validation.py` | Data-quality gate (fields, endpoints, timestamps, amounts, tags, duplicates, self-loops); reports issues, never raises on bad data |
| `report.py` | The markdown report, copied from the computed numbers |
| `cli.py` | `generate` / `features` / `score` / `report` / `check` (CI exit 0/1/2) / `demo` / `serve` (stdlib `http.server` on 127.0.0.1: `POST /score`, `POST /features`, `POST /report`, `GET /report`, `GET /health`) |
| `demo.py` | End-to-end narrative with asserts: determinism, recall, both decoys, the as-of canary, check exit codes, live localhost serve round-trip |
| `fixtures/` | The seeded graph itself (`sample_graph.json`, 72 nodes, 123 edges) with pinned totals |

## Evals

`python3 evals/run_evals.py` → **14/14 golden evals**, report committed at `evals/eval_report.json` (md5 `fe6e17587f7d794f590a5d113023f009`, byte-identical across 3 verified runs):

- **E1** generator determinism — seed 42 graph bytes pinned by md5
- **E2** headline counts (72 nodes, 123 edges, 20 planted bad, validates clean)
- **E3** planted-pattern recall pinned at 20/20 = 1.0, missed = none
- **E4** decoy proof (hub 0.026316 with no flags < planted minimum 0.125; payroll 0.0, no flags)
- **E5** per-pattern scores pinned (cycle 0.45, peel 0.45, smurf 0.40, layered 0.5 / 0.25 / 0.125)
- **E6** provenance pinned (cycle path, peel amounts, 5 smurfing intermediaries, layered path to sanctioned)
- **E7** as-of leakage canary (FUTURE_01 exposure 0.0 at ts=50 → 0.5 at ts=90)
- **E8** Tarjan: exactly one multi-node SCC in the seeded graph; a 5,000-node chain resolves iteratively
- **E9** personalized PageRank pinned (sanctioned 0.38346, hub 0.108647; mass sums to 1)
- **E10** degree normalisation on a hand-built hub (exact 0.05 vs 0.5 for a direct single-successor node)
- **E11** CLI `check` exit codes 0 / 2
- **E12** serve round-trip matches local score + report exactly
- **E13** bundled fixture pinned (72 nodes, 123 edges, validates clean)
- **E14** report determinism + the honesty line

Unit tests: `python3 -m unittest discover -s tests` → **66 hermetic tests**, including a no-network enforcement test (sockets stubbed), hand-built algorithm cases (Tarjan on cycles/DAGs/bridges, a 5,000-node chain and a 3,000-node cycle, exact k-hop normalisation arithmetic, PageRank convergence), detector edge cases (a rising-amount chain and a short chain the peel detector must reject; smurfing with and without convergence), the as-of leakage tests, validation defects, CLI exit codes, and serve round-trips.

## Development loop — what the tests actually caught

Two real bugs, both caught by this repo's own tests before anything shipped, each now pinned by a regression test and an eval:

1. **The generator minted duplicate transaction pairs.** Background targets were drawn *with* replacement per source, so the "123-edge" graph first came out with 126 edges containing 5 duplicate (src, dst) pairs — a graph whose adjacency the `Graph` class silently deduplicated, meaning edge counts and pair counts disagreed depending on which layer you asked. The no-duplicate-pairs test failed, the sampler now draws targets without replacement, and the headline counts (123 edges, dataset md5) are pinned in E1/E2 so it cannot drift back.
2. **Synchronous label propagation oscillates forever on a mutual pair.** With all labels updated at once, two nodes pointing at each other adopt each other's label simultaneously, swap back next round, and never converge — the dense-pair test caught the pair ending in *different* communities. Updates are now asynchronous in sorted node order (each adoption is visible to the next node in the same round), which converges and stays deterministic; the algorithm's docstring says why, so nobody "simplifies" it back.

One validated design decision worth naming: on the reversed graph, personalized PageRank ranks the convergence node *below* the seed but *above* its feeders when paths merge — an early test draft expected the opposite ordering and was wrong about the walk's arithmetic, not the code. The eval pins the computed ordering (E9) rather than the intuitive one.

## Scope and honest limits

- **NOT compliance-grade.** No sanctions-list screening, no case management, no entity resolution, no SAR workflow — this kit models only the graph-analytics loop named in the JD.
- **Planted labels are a teaching device.** Real graph risk grades against analyst dispositions and confirmed cases; recall of 1.0 against planted ground truth says the detectors implement their definitions, not that real smurfing is this clean.
- **Single-machine, in-memory.** 72 nodes is a teaching graph. The algorithms are O(V·E)-ish and honest about it; the large-scale version of this problem (the JD's actual setting) needs partitioned storage and incremental computation this kit does not attempt.
- **Exposure is a walk probability, not a loss estimate.** The k-hop score answers "how strongly is this node connected to the seed, degree-adjusted" — calibrating it against realised outcomes is a modelling step beyond this kit's scope.
- **Timestamps are integer days.** The as-of discipline is identical with real timestamps, but windowing, sessions, and intraday ordering are not modelled.
- **The API is a demo surface.** It binds 127.0.0.1 only, holds its graph in memory, and resets on restart.

## Why this project

The graph-analytics gap the TRM Labs JD names is not "can you run a graph library" — it is "can you reason about entity behaviour at graph scale without drowning in false structure." This project practises exactly that reasoning end-to-end: implement the algorithms so their behaviour can be audited, plant decoys that punish the naive version of each idea, refuse to let features read the future, and attach the evidence to every flag — with every number reproducible from a seed and pinned by an eval.
