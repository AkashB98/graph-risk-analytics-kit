"""Feature-table and scoring tests, incl. the as-of leakage canary
and the decoy proofs."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features import build_feature_table
from generator import HUB, bad_node_ids, generate_dataset
from graph import build_graph
from scoring import (detect_peel_chains, detect_smurfing, planted_recall,
                     score_graph)
from tests.helpers import make_dataset


def _by_node(rows):
    return {r["node_id"]: r for r in rows}


class TestAsOf(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def test_future_edge_does_not_leak(self):
        early = _by_node(build_feature_table(self.data, as_of=50))
        late = _by_node(build_feature_table(self.data, as_of=90))
        self.assertEqual(early["FUTURE_01"]["khop_exposure"], 0.0)
        self.assertEqual(early["FUTURE_01"]["out_degree"], 0)
        self.assertIsNone(early["FUTURE_01"]["hops_to_sanctioned"])
        self.assertEqual(late["FUTURE_01"]["khop_exposure"], 0.5)
        self.assertEqual(late["FUTURE_01"]["hops_to_sanctioned"], 1)

    def test_early_table_uses_only_early_edges(self):
        rows = build_feature_table(self.data, as_of=50)
        total_out = sum(r["out_amount"] for r in rows)
        expected = sum(e["amount"] for e in self.data["edges"]
                       if e["ts"] <= 50)
        self.assertEqual(total_out, round(expected, 2))

    def test_layered_path_absent_before_it_happens(self):
        rows = _by_node(build_feature_table(self.data, as_of=5))
        self.assertEqual(rows["LAYER_02"]["khop_exposure"], 0.0)
        rows = _by_node(build_feature_table(self.data, as_of=12))
        self.assertEqual(rows["LAYER_02"]["khop_exposure"], 0.5)

    def test_as_of_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            build_feature_table(self.data, as_of=91)
        with self.assertRaises(ValueError):
            build_feature_table(self.data, as_of=-1)


class TestScoringSeeded(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()
        self.result = score_graph(self.data)
        self.rows = _by_node(self.result["rows"])

    def test_planted_recall_is_perfect(self):
        rec = planted_recall(self.data)
        self.assertEqual((rec["planted_bad"], rec["caught"], rec["recall"]),
                         (20, 20, 1.0))
        self.assertEqual(rec["missed"], [])

    def test_hub_decoy_stays_quiet(self):
        hub = self.rows[HUB]
        self.assertEqual(hub["flags"], [])
        self.assertEqual(hub["risk_score"], 0.026316)
        bad_min = min(self.rows[n]["risk_score"]
                      for n in bad_node_ids(self.data))
        self.assertEqual(bad_min, 0.125)
        self.assertLess(hub["risk_score"], bad_min)

    def test_payroll_decoy_stays_quiet(self):
        self.assertEqual(self.rows["PAYROLL_01"]["flags"], [])
        self.assertEqual(self.rows["PAYROLL_01"]["risk_score"], 0.0)

    def test_cycle_members_flagged_with_provenance(self):
        for member in ("CYCLE_A", "CYCLE_B", "CYCLE_C", "CYCLE_D"):
            flags = self.rows[member]["flags"]
            self.assertEqual([f["pattern"] for f in flags],
                             ["round_trip_cycle"])
            self.assertEqual(flags[0]["provenance"]["scc"],
                             ["CYCLE_A", "CYCLE_B", "CYCLE_C", "CYCLE_D"])
            self.assertEqual(self.rows[member]["risk_score"], 0.45)

    def test_peel_chain_flagged_with_amounts(self):
        flag = self.rows["PEEL_03"]["flags"][0]
        self.assertEqual(flag["pattern"], "peel_chain")
        self.assertEqual(flag["provenance"]["amounts"],
                         [10000.0, 9000.0, 8100.0, 7290.0, 6561.0])
        self.assertEqual(flag["provenance"]["path"][0], "PEEL_00")
        self.assertEqual(flag["provenance"]["path"][-1], "PEEL_05")

    def test_smurfing_roles_flagged(self):
        for node in ("SMURF_SRC", "SMURF_M3", "SMURF_SINK"):
            flags = self.rows[node]["flags"]
            self.assertEqual([f["pattern"] for f in flags],
                             ["smurfing_fan_out_in"])
            self.assertEqual(len(flags[0]["provenance"]["intermediaries"]), 5)
        self.assertEqual(
            self.rows["SMURF_M3"]["flags"][0]["provenance"]["role"],
            "intermediary")

    def test_layered_scores_decay_by_hop(self):
        self.assertEqual(self.rows["LAYER_02"]["risk_score"], 0.5)
        self.assertEqual(self.rows["LAYER_01"]["risk_score"], 0.25)
        self.assertEqual(self.rows["LAYER_00"]["risk_score"], 0.125)
        prov = self.rows["LAYER_00"]["flags"][0]["provenance"]
        self.assertEqual(prov["path_to_sanctioned"],
                         ["LAYER_00", "LAYER_01", "LAYER_02",
                          "SANCTIONED_01"])

    def test_every_flag_has_provenance(self):
        for row in self.result["rows"]:
            for flag in row["flags"]:
                self.assertIn("pattern", flag)
                self.assertTrue(flag["provenance"])

    def test_flagged_count(self):
        # 20 planted bad + FUTURE_01 (its ts=88 edge is live at as-of 90)
        self.assertEqual(self.result["flagged_count"], 21)

    def test_scc_feature_marks_only_cycle(self):
        cyclic = [r["node_id"] for r in self.result["rows"] if r["in_cycle"]]
        self.assertEqual(cyclic,
                         ["CYCLE_A", "CYCLE_B", "CYCLE_C", "CYCLE_D"])


class TestDetectorsHandBuilt(unittest.TestCase):
    def test_peel_detector_rejects_rising_amounts(self):
        ds = make_dataset(
            {f"P{i}": "peel" for i in range(6)},
            [(f"P{i}", f"P{i + 1}", 1000.0 * (i + 1), 10 + i, "peel")
             for i in range(5)])
        g = build_graph(ds["nodes"], ds["edges"])
        self.assertEqual(detect_peel_chains(g), [])

    def test_peel_detector_rejects_short_chain(self):
        ds = make_dataset(
            {f"P{i}": "peel" for i in range(4)},
            [(f"P{i}", f"P{i + 1}", 9000.0 - 500 * i, 10 + i, "peel")
             for i in range(3)])
        g = build_graph(ds["nodes"], ds["edges"])
        self.assertEqual(detect_peel_chains(g), [])

    def test_smurf_detector_needs_convergence(self):
        nodes = {"SRC": "smurf_source", "SINK": "smurf_sink"}
        nodes.update({f"M{i}": "smurf_mid" for i in range(5)})
        edges = []
        for i in range(5):
            edges.append(("SRC", f"M{i}", 900.0, 40, "smurf"))
            edges.append((f"M{i}", "SINK", 880.0, 41, "smurf"))
        ds = make_dataset(nodes, edges)
        found = detect_smurfing(build_graph(ds["nodes"], ds["edges"]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["sink"], "SINK")
        # Break convergence: mids point at distinct sinks -> no finding.
        nodes2 = dict(nodes)
        edges2 = []
        for i in range(5):
            nodes2[f"T{i}"] = "legit"
            edges2.append(("SRC", f"M{i}", 900.0, 40, "smurf"))
            edges2.append((f"M{i}", f"T{i}", 880.0, 41, "smurf"))
        ds2 = make_dataset(nodes2, edges2)
        self.assertEqual(detect_smurfing(
            build_graph(ds2["nodes"], ds2["edges"])), [])


if __name__ == "__main__":
    unittest.main()
