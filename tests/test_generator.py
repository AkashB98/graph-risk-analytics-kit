"""Generator tests: determinism, headline counts, planted shapes."""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import (HUB, SANCTIONED, bad_node_ids, dataset_to_json,
                       generate_dataset)
from validation import validate_dataset


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def test_deterministic_bytes(self):
        self.assertEqual(dataset_to_json(generate_dataset()),
                         dataset_to_json(generate_dataset()))
        md5 = hashlib.md5(dataset_to_json(self.data).encode()).hexdigest()
        self.assertEqual(md5, "01605c3e91ea264ce79abfbc0332cb9a")

    def test_headline_counts(self):
        self.assertEqual(self.data["node_count"], 72)
        self.assertEqual(len(self.data["edges"]), 123)
        self.assertEqual(len(bad_node_ids(self.data)), 20)
        self.assertEqual(validate_dataset(self.data), [])

    def test_all_timestamps_in_range(self):
        self.assertTrue(all(1 <= e["ts"] <= 90 for e in self.data["edges"]))

    def test_peel_amounts_fall_ten_percent(self):
        peel = [e for e in self.data["edges"] if e["planted"] == "peel"]
        amounts = [e["amount"] for e in sorted(peel, key=lambda e: e["ts"])]
        self.assertEqual(amounts, [10000.0, 9000.0, 8100.0, 7290.0, 6561.0])

    def test_cycle_edges_close_the_ring(self):
        cyc = {(e["src"], e["dst"]) for e in self.data["edges"]
               if e["planted"] == "cycle"}
        self.assertEqual(cyc, {("CYCLE_A", "CYCLE_B"), ("CYCLE_B", "CYCLE_C"),
                               ("CYCLE_C", "CYCLE_D"), ("CYCLE_D", "CYCLE_A")})

    def test_hub_degree_and_sanctioned_edge(self):
        out_deg = sum(1 for e in self.data["edges"] if e["src"] == HUB)
        in_deg = sum(1 for e in self.data["edges"] if e["dst"] == HUB)
        self.assertEqual((in_deg, out_deg), (18, 19))
        self.assertTrue(any(e["src"] == HUB and e["dst"] == SANCTIONED
                            for e in self.data["edges"]))

    def test_payroll_fans_out_to_twelve(self):
        outs = [e["dst"] for e in self.data["edges"]
                if e["src"] == "PAYROLL_01"]
        self.assertEqual(len(outs), 12)

    def test_future_edge_timestamp(self):
        fut = [e for e in self.data["edges"] if e["planted"] == "future"]
        self.assertEqual(len(fut), 1)
        self.assertEqual((fut[0]["src"], fut[0]["dst"], fut[0]["ts"]),
                         ("FUTURE_01", SANCTIONED, 88))

    def test_no_self_loops_no_duplicate_pairs(self):
        pairs = [(e["src"], e["dst"]) for e in self.data["edges"]]
        self.assertTrue(all(s != d for s, d in pairs))
        self.assertEqual(len(pairs), len(set(pairs)))

    def test_small_legit_count_rejected(self):
        with self.assertRaises(ValueError):
            generate_dataset(legit_count=10)


if __name__ == "__main__":
    unittest.main()
