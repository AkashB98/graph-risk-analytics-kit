"""Validation gate tests."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset
from validation import validate_dataset


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.data = generate_dataset()

    def test_seeded_data_is_clean(self):
        self.assertEqual(validate_dataset(self.data), [])

    def test_not_an_object(self):
        self.assertEqual(validate_dataset([1, 2]),
                         ["dataset must be a JSON object"])

    def test_unknown_endpoint_node(self):
        bad = copy.deepcopy(self.data)
        bad["edges"][0]["dst"] = "NOPE"
        self.assertTrue(any("unknown dst" in i
                            for i in validate_dataset(bad)))

    def test_duplicate_edge_id(self):
        bad = copy.deepcopy(self.data)
        bad["edges"][1]["edge_id"] = bad["edges"][0]["edge_id"]
        self.assertTrue(any("duplicate edge_id" in i
                            for i in validate_dataset(bad)))

    def test_bad_timestamp_and_amount(self):
        bad = copy.deepcopy(self.data)
        bad["edges"][0]["ts"] = 999
        bad["edges"][1]["amount"] = -5
        issues = validate_dataset(bad)
        self.assertTrue(any("bad ts" in i for i in issues))
        self.assertTrue(any("bad amount" in i for i in issues))

    def test_self_loop_flagged(self):
        bad = copy.deepcopy(self.data)
        bad["edges"][0]["dst"] = bad["edges"][0]["src"]
        self.assertTrue(any("self-loop" in i
                            for i in validate_dataset(bad)))

    def test_bad_planted_tag(self):
        bad = copy.deepcopy(self.data)
        bad["edges"][0]["planted"] = "mystery"
        self.assertTrue(any("bad planted tag" in i
                            for i in validate_dataset(bad)))


if __name__ == "__main__":
    unittest.main()
