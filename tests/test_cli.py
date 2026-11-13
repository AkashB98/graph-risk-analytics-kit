"""CLI tests: exit codes, subcommands, serve round-trip."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cli import EXIT_ERROR, EXIT_OK, main as cli_main, make_server, reset_state
from generator import dataset_to_json, generate_dataset
from report import build_markdown_report
from scoring import score_graph


def _run(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return cli_main(argv)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="graph-risk-test-")
        self.path = os.path.join(self.tmp, "graph.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(dataset_to_json(generate_dataset()))

    def test_check_seeded_passes(self):
        self.assertEqual(_run(["check", "--input", self.path]), EXIT_OK)

    def test_check_missing_file_is_error(self):
        self.assertEqual(
            _run(["check", "--input", "/tmp/no-such-graph-xyz.json"]),
            EXIT_ERROR)

    def test_check_corrupt_file_is_error(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write('{"nodes": []}')
        self.assertEqual(_run(["check", "--input", bad]), EXIT_ERROR)

    def test_generate_then_score_round_trip(self):
        out = os.path.join(self.tmp, "gen.json")
        self.assertEqual(_run(["generate", "--out", out]), EXIT_OK)
        scored = os.path.join(self.tmp, "scored.json")
        self.assertEqual(
            _run(["score", "--input", out, "--out", scored]), EXIT_OK)
        with open(scored, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["flagged_count"], 21)

    def test_features_respects_as_of(self):
        out = os.path.join(self.tmp, "feat.json")
        self.assertEqual(_run(["features", "--input", self.path,
                               "--as-of", "50", "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            payload = json.load(fh)
        future = [r for r in payload["rows"]
                  if r["node_id"] == "FUTURE_01"][0]
        self.assertEqual(future["khop_exposure"], 0.0)

    def test_features_bad_as_of_is_error(self):
        self.assertEqual(_run(["features", "--input", self.path,
                               "--as-of", "999"]), EXIT_ERROR)

    def test_report_matches_builder(self):
        out = os.path.join(self.tmp, "report.md")
        self.assertEqual(
            _run(["report", "--input", self.path, "--out", out]), EXIT_OK)
        with open(out, encoding="utf-8") as fh:
            self.assertEqual(fh.read(),
                             build_markdown_report(generate_dataset()))

    def test_serve_round_trip(self):
        data = generate_dataset()
        reset_state(data)
        server = make_server(0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=10) as resp:
                self.assertEqual(json.loads(resp.read()), {"status": "ok"})
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/score", data=b"{}",
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                served = json.loads(resp.read())
            self.assertEqual(served["flagged_count"],
                             score_graph(data)["flagged_count"])
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/report", timeout=10) as resp:
                self.assertEqual(resp.read().decode(),
                                 build_markdown_report(data))
        finally:
            server.shutdown()
            server.server_close()
            reset_state()


if __name__ == "__main__":
    unittest.main()
