"""Graph algorithm tests: Tarjan (iterative), k-hop normalisation,
personalized PageRank, flagged paths, label propagation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph import (Graph, khop_decayed_exposure, label_propagation,
                   paths_from_flagged, personalized_pagerank,
                   strongly_connected_components)
from tests.helpers import graph_of


class TestTarjan(unittest.TestCase):
    def test_cycle_is_one_component(self):
        g = graph_of(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        self.assertEqual(strongly_connected_components(g),
                         [["A", "B", "C"]])

    def test_dag_all_singletons(self):
        g = graph_of(["A", "B", "C"], [("A", "B"), ("B", "C")])
        self.assertEqual(strongly_connected_components(g),
                         [["A"], ["B"], ["C"]])

    def test_two_cycles_plus_bridge(self):
        g = graph_of(["A", "B", "C", "D", "E"],
                     [("A", "B"), ("B", "A"), ("B", "C"),
                      ("C", "D"), ("D", "C"), ("D", "E")])
        self.assertEqual(strongly_connected_components(g),
                         [["A", "B"], ["C", "D"], ["E"]])

    def test_self_loop_stays_singleton_component(self):
        g = graph_of(["A", "B"], [("A", "A"), ("A", "B")])
        self.assertEqual(strongly_connected_components(g),
                         [["A"], ["B"]])

    def test_deep_chain_does_not_recurse(self):
        n = 5000
        ids = [f"N{i:05d}" for i in range(n)]
        g = graph_of(ids, [(ids[i], ids[i + 1]) for i in range(n - 1)])
        comps = strongly_connected_components(g)
        self.assertEqual(len(comps), n)

    def test_deep_cycle_does_not_recurse(self):
        n = 3000
        ids = [f"N{i:05d}" for i in range(n)]
        pairs = [(ids[i], ids[(i + 1) % n]) for i in range(n)]
        comps = strongly_connected_components(graph_of(ids, pairs))
        self.assertEqual(comps, [ids])


class TestKhopExposure(unittest.TestCase):
    def test_seed_itself_has_zero_forward_exposure(self):
        g = graph_of(["S", "A"], [("A", "S")])
        exp = khop_decayed_exposure(g, ["S"])
        self.assertEqual(exp["S"], 0.0)
        self.assertEqual(exp["A"], 0.5)

    def test_decay_compounds_over_hops(self):
        g = graph_of(["S", "A", "B"], [("B", "A"), ("A", "S")])
        exp = khop_decayed_exposure(g, ["S"], k=3, decay=0.5)
        self.assertEqual(exp["A"], 0.5)
        self.assertEqual(exp["B"], 0.25)

    def test_degree_normalisation_defuses_hub(self):
        pairs = [("HUB", f"L{i}") for i in range(9)] + [("HUB", "S"),
                                                         ("X", "S")]
        g = graph_of(["HUB", "S", "X"] + [f"L{i}" for i in range(9)], pairs)
        exp = khop_decayed_exposure(g, ["S"])
        self.assertEqual(exp["X"], 0.5)          # sole successor is the seed
        self.assertEqual(exp["HUB"], 0.05)       # 0.5 spread over 10 edges
        self.assertLess(exp["HUB"], exp["X"])

    def test_unreachable_node_zero(self):
        g = graph_of(["S", "Z"], [])
        self.assertEqual(khop_decayed_exposure(g, ["S"])["Z"], 0.0)


class TestPageRank(unittest.TestCase):
    def test_mass_sums_to_one(self):
        g = graph_of(["S", "A", "B"], [("A", "S"), ("B", "A")])
        pr = personalized_pagerank(g.reversed(), ["S"])
        self.assertAlmostEqual(sum(pr.values()), 1.0, places=4)

    def test_seed_ranks_first_on_reversed_graph(self):
        g = graph_of(["S", "A", "B"], [("A", "S"), ("B", "A"), ("B", "S")])
        pr = personalized_pagerank(g.reversed(), ["S"])
        self.assertEqual(max(pr, key=lambda n: pr[n]), "S")
        # On the reversed graph B is fed by BOTH S and A, so B > A:
        # the walk accumulates where paths converge.
        self.assertGreater(pr["B"], pr["A"])

    def test_deterministic(self):
        g = graph_of(["S", "A", "B", "C"],
                     [("A", "S"), ("B", "A"), ("C", "B"), ("C", "S")])
        self.assertEqual(personalized_pagerank(g, ["S"]),
                         personalized_pagerank(g, ["S"]))

    def test_empty_seeds_raise(self):
        g = graph_of(["A"], [])
        with self.assertRaises(ValueError):
            personalized_pagerank(g, [])


class TestFlaggedPaths(unittest.TestCase):
    def test_paths_start_at_flagged_and_are_shortest(self):
        g = graph_of(["F", "A", "B", "C"],
                     [("F", "A"), ("A", "C"), ("F", "B"), ("B", "C")])
        out = paths_from_flagged(g, ["F"])
        self.assertEqual(out["F"]["C"], ["F", "A", "C"])  # sorted BFS order
        self.assertEqual(out["F"]["F"], ["F"])

    def test_only_flagged_nodes_are_roots(self):
        g = graph_of(["F", "A"], [("F", "A"), ("A", "F")])
        out = paths_from_flagged(g, ["A"])
        self.assertEqual(list(out.keys()), ["A"])

    def test_unknown_flagged_node_skipped(self):
        g = graph_of(["A"], [])
        self.assertEqual(paths_from_flagged(g, ["ZZZ"]), {})


class TestLabelPropagation(unittest.TestCase):
    def test_deterministic_and_stable(self):
        g = graph_of(["A", "B", "C", "D"],
                     [("A", "B"), ("B", "C"), ("C", "D")])
        first = label_propagation(g)
        self.assertEqual(first, label_propagation(g))

    def test_isolated_node_keeps_own_label(self):
        g = graph_of(["A", "Z"], [("A", "A")])
        self.assertEqual(label_propagation(g)["Z"], "Z")

    def test_dense_pair_shares_a_label(self):
        g = graph_of(["A", "B"], [("A", "B"), ("B", "A")])
        labels = label_propagation(g)
        self.assertEqual(labels["A"], labels["B"])


if __name__ == "__main__":
    unittest.main()
