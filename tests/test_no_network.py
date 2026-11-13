"""No-network enforcement: with sockets blocked, generating,
validating, featuring, scoring and reporting must all still work.
(``serve`` is the only intentional exception — it binds loopback on
demand, and is not used here.)"""

import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Blocker:
    def __init__(self, *a, **k):
        raise RuntimeError("network access blocked in hermetic test")


class TestNoNetwork(unittest.TestCase):
    def setUp(self):
        self._real_socket = socket.socket
        socket.socket = _Blocker
        import urllib.request as urlreq
        self._real_urlopen = urlreq.urlopen
        urlreq.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("network access blocked in hermetic test"))

    def tearDown(self):
        socket.socket = self._real_socket
        import urllib.request as urlreq
        urlreq.urlopen = self._real_urlopen

    def test_full_pipeline_offline(self):
        from generator import generate_dataset
        from report import build_markdown_report
        from scoring import planted_recall, score_graph
        from validation import validate_dataset
        data = generate_dataset()
        self.assertEqual(validate_dataset(data), [])
        self.assertEqual(planted_recall(data)["recall"], 1.0)
        self.assertEqual(score_graph(data)["flagged_count"], 21)
        self.assertIn("HUB_EXCHANGE", build_markdown_report(data))

    def test_no_module_opens_sockets_at_import(self):
        for mod in ("generator", "validation", "graph", "features",
                    "scoring", "report", "cli", "demo"):
            sys.modules.pop(mod, None)
        import cli, demo, features, generator, graph, report, scoring, validation  # noqa: F401,E501
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
