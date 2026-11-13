"""CLI: generate | features | score | report | check | demo | serve.

SYNTHETIC DATA ONLY — every entity is fictional and every dataset
handled here is fabricated sample data. NOT compliance-grade tooling.

Exit codes:
  check : 0 = pass, 1 = quality breach (planted-pattern recall below
          1.0, a decoy scoring at/above a planted pattern, or as-of
          leakage), 2 = usage / IO / data-quality error
  others: 0 = success, 2 = usage / IO error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from features import build_feature_table  # noqa: E402
from generator import HUB, bad_node_ids, dataset_to_json, generate_dataset  # noqa: E402
from report import build_markdown_report  # noqa: E402
from scoring import planted_recall, score_graph  # noqa: E402
from validation import validate_dataset  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True)


def load_dataset(path: str) -> Dict:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("dataset file must contain a JSON object")
    return data


def _load_or_error(path: str) -> Optional[Dict]:
    try:
        return load_dataset(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
    return None


def _validated(args):
    data = _load_or_error(args.input)
    if data is None:
        return None, EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}", file=sys.stderr)
        return None, EXIT_ERROR
    return data, EXIT_OK


def _write_out(args, text: str, summary: str) -> int:
    if getattr(args, "out", None):
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            print(f"error: cannot write {args.out}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        print(summary)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_generate(args) -> int:
    data = generate_dataset(seed=args.seed)
    return _write_out(args, dataset_to_json(data),
                      f"generated synthetic graph: {data['node_count']} "
                      f"nodes, {len(data['edges'])} edges "
                      f"(seed={args.seed}) -> {args.out}")


def cmd_features(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    as_of = data["max_ts"] if args.as_of is None else args.as_of
    try:
        rows = build_feature_table(data, as_of=as_of)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    payload = {"as_of": as_of, "rows": rows}
    return _write_out(args, canonical(payload) + "\n",
                      f"features (as_of={args.as_of}) -> {args.out}")


def cmd_score(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    result = score_graph(data, as_of=args.as_of)
    return _write_out(args, canonical(result) + "\n",
                      f"score (as_of={result['as_of']}, "
                      f"flagged={result['flagged_count']}) -> {args.out}")


def cmd_report(args) -> int:
    data, code = _validated(args)
    if data is None:
        return code
    return _write_out(args, build_markdown_report(data, as_of=args.as_of),
                      f"report -> {args.out}")


def _quality_breaches(data: Dict):
    """The check gate's quality rules, shared by CLI and evals."""
    breaches = []
    recall = planted_recall(data)
    if recall["recall"] < 1.0:
        breaches.append(f"planted recall {recall['recall']} < 1.0 "
                        f"(missed {recall['missed']})")
    result = score_graph(data)
    by_node = {r["node_id"]: r for r in result["rows"]}
    bad_min = min(by_node[n]["risk_score"] for n in bad_node_ids(data))
    for decoy in (HUB, "PAYROLL_01"):
        if by_node[decoy]["flags"]:
            breaches.append(f"decoy {decoy} carries flags")
        if by_node[decoy]["risk_score"] >= bad_min:
            breaches.append(f"decoy {decoy} risk "
                            f"{by_node[decoy]['risk_score']} >= planted "
                            f"minimum {bad_min}")
    early = score_graph(data, as_of=50)
    future = [r for r in early["rows"] if r["node_id"] == "FUTURE_01"][0]
    if future["khop_exposure"] != 0.0 or future["flags"]:
        breaches.append("as-of leakage: FUTURE_01 visible at as_of=50")
    return breaches, recall, by_node


def cmd_check(args) -> int:
    data = _load_or_error(args.input)
    if data is None:
        return EXIT_ERROR
    issues = validate_dataset(data)
    if issues:
        for issue in issues[:20]:
            print(f"data-quality: {issue}")
        print(f"check FAIL (data quality): {len(issues)} issue(s)")
        return EXIT_ERROR
    breaches, recall, by_node = _quality_breaches(data)
    print(f"nodes={data['node_count']} edges={len(data['edges'])} "
          f"planted_recall={recall['recall']} "
          f"hub_risk={by_node[HUB]['risk_score']}")
    if breaches:
        for b in breaches:
            print(f"check FAIL: {b}")
        return EXIT_FAIL
    print("check PASS")
    return EXIT_OK


def cmd_demo(args) -> int:
    import demo as demo_mod
    try:
        demo_mod.main()
    except AssertionError as exc:
        print(f"demo FAILED: {exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


# ------------------------------------------------------------------- serve

class _State:
    def __init__(self):
        self.data: Dict = generate_dataset()


_STATE = _State()


def get_state() -> _State:
    return _STATE


def reset_state(data: Optional[Dict] = None) -> None:
    _STATE.data = data if data is not None else generate_dataset()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, payload: Any) -> None:
        self._send(code, (canonical(payload) + "\n").encode(),
                   "application/json")

    def _dataset_from(self, body: Dict) -> Optional[Dict]:
        if "dataset" not in body:
            return _STATE.data
        candidate = body["dataset"]
        if validate_dataset(candidate):
            return None
        _STATE.data = candidate
        return candidate

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send_json(200, {"status": "ok"})
        if self.path == "/report":
            return self._send(200, build_markdown_report(
                _STATE.data).encode(), "text/markdown; charset=utf-8")
        return self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):  # noqa: N802
        if self.path not in ("/score", "/features", "/report"):
            return self._send_json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw.strip() else {}
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            data = self._dataset_from(body)
            if data is None:
                return self._send_json(400, {"error": "data quality"})
            as_of = body.get("as_of")
            if self.path == "/score":
                return self._send_json(200, score_graph(data, as_of=as_of))
            if self.path == "/features":
                use_as_of = data["max_ts"] if as_of is None else as_of
                return self._send_json(200, {
                    "as_of": use_as_of,
                    "rows": build_feature_table(data, as_of=use_as_of)})
            return self._send_json(
                200, {"report": build_markdown_report(data, as_of=as_of)})
        except (ValueError, TypeError, KeyError) as exc:
            return self._send_json(400, {"error": f"bad request: {exc}"})

    def log_message(self, *a: Any) -> None:
        pass


def make_server(port: int) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), _Handler)


def cmd_serve(args) -> int:
    if args.input:
        data = _load_or_error(args.input)
        if data is None:
            return EXIT_ERROR
        reset_state(data)
    server = make_server(args.port)
    print(f"serving on http://127.0.0.1:{args.port}  "
          f"(POST /score, POST /features, POST /report, "
          f"GET /report, GET /health)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph-risk-analytics-kit",
        description="Graph risk analytics on a synthetic timestamped "
                    "transaction graph: SCC cycles, peel chains, "
                    "smurfing, sanctioned exposure — as-of clean.")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="generate the synthetic graph")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", default=None)
    g.set_defaults(func=cmd_generate)

    for name, func, helptext in [
            ("features", cmd_features, "as-of feature table"),
            ("score", cmd_score, "flags + risk scores with provenance"),
            ("report", cmd_report, "markdown report")]:
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--input", required=True)
        s.add_argument("--as-of", type=int, default=None)
        s.add_argument("--out", default=None)
        s.set_defaults(func=func)

    c = sub.add_parser("check", help="CI gate: exit 0 pass / 1 breach / 2 error")
    c.add_argument("--input", required=True)
    c.set_defaults(func=cmd_check)

    sub.add_parser("demo", help="run the end-to-end demo").set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="localhost JSON/markdown API")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--input", default=None)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
