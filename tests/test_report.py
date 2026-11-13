"""Report tests: determinism and required content."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generator import generate_dataset
from report import build_markdown_report


class TestReport(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(build_markdown_report(generate_dataset()),
                         build_markdown_report(generate_dataset()))

    def test_honesty_line_and_decoy_numbers(self):
        md = build_markdown_report(generate_dataset())
        self.assertIn("NOT compliance-grade", md)
        self.assertIn("0.026316", md)   # hub risk, printed from the data
        self.assertIn("Caught 20 of 20", md)


if __name__ == "__main__":
    unittest.main()
