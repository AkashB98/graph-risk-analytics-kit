"""Graph algorithms — stdlib only, deterministic, iterative.

Every algorithm here is implemented by hand (no networkx) so its
behaviour can be audited line by line and reproduces exactly:

  * ``strongly_connected_components`` — Tarjan's algorithm written
    ITERATIVELY (an explicit work stack, never recursion), so a
    10,000-node chain cannot hit Python's recursion limit. A
    **strongly connected component** — a set of nodes that can all
    reach each other by following directed edges — with more than
    one node is a directed cycle.
  * ``khop_decayed_exposure`` — risk flowing backwards from seed
    nodes for k hops, **decayed** — worth less at each hop — and
    **degree-normalised**: a node's contribution is divided by its
    out-degree, so a high-degree hub spreads its risk thin instead
    of flooding its neighbourhood.
  * ``personalized_pagerank`` — **PageRank** — a random-walk score
    where a walker follows edges and occasionally restarts —
    personalised by restarting only at the seed set, computed by
    **power iteration** — repeating the update until it stops
    changing. Run on reversed edges it scores how strongly a node
    feeds the seeds.
  * ``paths_from_flagged`` — breadth-first search (BFS) — exploring
    a graph level by level — that returns actual paths, but ONLY
    outward from a caller-supplied flagged set. There is
    deliberately no arbitrary pair path-query function: every path
    this kit emits is provenance for a flag ("path from a flagged
    node to X"), never an open-ended graph query API.
  * ``label_propagation`` — **label propagation** — each node adopts
    the most common label among its neighbours, repeated — with
    sorted tie-breaking so the result is deterministic.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Set


class Graph:
    """Directed graph over string node ids, deterministically ordered."""

    def __init__(self, node_ids, edges):
        self.nodes = sorted(node_ids)
        self.node_set = set(self.nodes)
        self.succ: Dict[str, List[str]] = {n: [] for n in self.nodes}
        self.pred: Dict[str, List[str]] = {n: [] for n in self.nodes}
        self.edges = list(edges)
        seen = set()
        for e in self.edges:
            s, d = e["src"], e["dst"]
            if (s, d) not in seen:
                seen.add((s, d))
                self.succ[s].append(d)
                self.pred[d].append(s)
        for n in self.nodes:
            self.succ[n].sort()
            self.pred[n].sort()

    def out_degree(self, node: str) -> int:
        return len(self.succ[node])

    def in_degree(self, node: str) -> int:
        return len(self.pred[node])

    def reversed(self) -> "Graph":
        rev = [{"src": e["dst"], "dst": e["src"], "amount": e["amount"],
                "ts": e["ts"], "planted": e.get("planted")}
               for e in self.edges]
        return Graph(self.nodes, rev)


def build_graph(nodes, edges, as_of=None) -> Graph:
    """Graph from rows, keeping only edges with ``ts <= as_of``."""
    kept = [e for e in edges if as_of is None or e["ts"] <= as_of]
    return Graph([n["node_id"] for n in nodes], kept)


# --------------------------------------------------------------- Tarjan

def strongly_connected_components(graph: Graph) -> List[List[str]]:
    """Iterative Tarjan SCC. Returns components sorted by first node,
    each component's members sorted."""
    index_of: Dict[str, int] = {}
    low: Dict[str, int] = {}
    on_stack: Set[str] = set()
    stack: List[str] = []
    result: List[List[str]] = []
    counter = [0]

    for root in graph.nodes:
        if root in index_of:
            continue
        # Work stack entries: (node, next successor position).
        work = [(root, 0)]
        while work:
            node, pos = work[-1]
            if pos == 0:
                index_of[node] = low[node] = counter[0]
                counter[0] += 1
                stack.append(node)
                on_stack.add(node)
            descended = False
            succs = graph.succ[node]
            while pos < len(succs):
                nxt = succs[pos]
                pos += 1
                if nxt not in index_of:
                    work[-1] = (node, pos)
                    work.append((nxt, 0))
                    descended = True
                    break
                elif nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            if descended:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                comp = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    comp.append(member)
                    if member == node:
                        break
                result.append(sorted(comp))
    result.sort(key=lambda c: c[0])
    return result


# ------------------------------------------------- k-hop decayed risk

def khop_decayed_exposure(graph: Graph, seeds, k: int = 3,
                          decay: float = 0.5) -> Dict[str, float]:
    """Degree-normalised, decayed exposure to ``seeds``.

    exposure_0(seed) = 1. At each hop, a node's new exposure is
    ``decay * mean over its successors of the previous hop's
    exposure`` — dividing by out-degree is the normalisation: a hub
    with 19 successors passes only 1/19 of a successor's risk back
    to itself, while a layered node with a single successor passes
    the full (decayed) amount. Total exposure sums hops 1..k.
    """
    seed_set = set(seeds)
    total = {n: 0.0 for n in graph.nodes}
    current = {n: (1.0 if n in seed_set else 0.0) for n in graph.nodes}
    for _hop in range(k):
        nxt = {}
        for node in graph.nodes:
            succs = graph.succ[node]
            if not succs:
                nxt[node] = 0.0
            else:
                nxt[node] = decay * sum(current[s] for s in succs) / len(succs)
        for node in graph.nodes:
            total[node] += nxt[node]
        current = nxt
    return {n: round(total[n], 6) for n in graph.nodes}


# ------------------------------------------------- personalized PageRank

def personalized_pagerank(graph: Graph, seeds, alpha: float = 0.85,
                          tol: float = 1e-12,
                          max_iter: int = 200) -> Dict[str, float]:
    """Power-iteration PageRank with restart concentrated on seeds.

    Dangling nodes (out-degree 0) redistribute their mass to the
    teleport set, so total mass stays 1.
    """
    seed_set = sorted(set(seeds))
    if not seed_set:
        raise ValueError("pagerank needs at least one seed")
    teleport = {n: (1.0 / len(seed_set) if n in seed_set else 0.0)
                for n in graph.nodes}
    rank = dict(teleport)
    for _ in range(max_iter):
        dangling = sum(rank[n] for n in graph.nodes
                       if graph.out_degree(n) == 0)
        nxt = {}
        for node in graph.nodes:
            incoming = sum(rank[p] / graph.out_degree(p)
                           for p in graph.pred[node])
            nxt[node] = ((1 - alpha) * teleport[node]
                         + alpha * (incoming
                                    + dangling * teleport[node]))
        delta = sum(abs(nxt[n] - rank[n]) for n in graph.nodes)
        rank = nxt
        if delta < tol:
            break
    return {n: round(rank[n], 6) for n in graph.nodes}


# ------------------------------------------------------- flagged paths

def paths_from_flagged(graph: Graph, flagged) -> Dict[str, Dict[str, List[str]]]:
    """BFS shortest paths outward from each flagged node.

    Returns ``{flagged_node: {reachable_node: [path...]}}``. This is
    the kit's only path surface: paths exist to explain a flag's
    provenance, so they always start at a flagged node.
    """
    out: Dict[str, Dict[str, List[str]]] = {}
    for start in sorted(set(flagged)):
        if start not in graph.node_set:
            continue
        paths = {start: [start]}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nxt in graph.succ[node]:
                if nxt not in paths:
                    paths[nxt] = paths[node] + [nxt]
                    queue.append(nxt)
        out[start] = paths
    return out


def hops_to_seeds(graph: Graph, seeds) -> Dict[str, object]:
    """Hop distance from each node TO the nearest seed, computed by
    BFS outward from the seeds on the reversed graph (reusing the
    flagged-path surface: the seeds are the flagged set). ``None``
    when no path exists."""
    rev_paths = paths_from_flagged(graph.reversed(), seeds)
    dist: Dict[str, object] = {n: None for n in graph.nodes}
    for seed_paths in rev_paths.values():
        for node, path in seed_paths.items():
            hops = len(path) - 1
            if dist[node] is None or hops < dist[node]:
                dist[node] = hops
    return dist


def path_to_seed(graph: Graph, node: str, seeds) -> List[str]:
    """The provenance path from ``node`` to its nearest seed: the
    flagged-path BFS run from the seeds on the reversed graph,
    reversed back into node -> ... -> seed order. Returns [] when
    the node cannot reach any seed."""
    rev_paths = paths_from_flagged(graph.reversed(), seeds)
    best = None
    for seed_paths in rev_paths.values():
        if node in seed_paths:
            candidate = list(reversed(seed_paths[node]))
            if best is None or len(candidate) < len(best):
                best = candidate
    return best or []


# ---------------------------------------------------- label propagation

def label_propagation(graph: Graph, max_iter: int = 50) -> Dict[str, str]:
    """Deterministic label propagation on the undirected view.

    ASYNCHRONOUS updates in sorted node order (each adoption is
    visible to the next node in the same round): synchronous updates
    oscillate forever on a two-node mutual pair — each node adopts
    the other's label at the same moment and they swap back and
    forth — while in-place updates converge. Each node adopts the
    most frequent label among its neighbours (successors +
    predecessors), ties broken by the smallest label; a node with
    no neighbours keeps its own label. Stops when a full round
    changes nothing.
    """
    labels = {n: n for n in graph.nodes}
    neighbours = {n: sorted(set(graph.succ[n]) | set(graph.pred[n]))
                  for n in graph.nodes}
    for _ in range(max_iter):
        changed = False
        for node in graph.nodes:
            nbrs = neighbours[node]
            if not nbrs:
                continue
            counts: Dict[str, int] = {}
            for nbr in nbrs:
                counts[labels[nbr]] = counts.get(labels[nbr], 0) + 1
            best = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if best != labels[node]:
                labels[node] = best
                changed = True
        if not changed:
            break
    return labels
