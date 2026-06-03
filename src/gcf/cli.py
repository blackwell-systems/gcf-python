"""GCF command-line interface: encode, decode, stats."""

import json
import sys

from .decode import decode
from .encode import encode
from .types import Edge, Payload, Symbol

USAGE = """gcf - token-optimized wire format for LLM tool responses

Usage:
  gcf encode [file]    Encode JSON payload to GCF (stdin if no file)
  gcf decode [file]    Decode GCF text to JSON (stdin if no file)
  gcf stats  [file]    Compare token counts: JSON vs GCF (stdin if no file)
  gcf version          Print version

Examples:
  gcf encode < payload.json
  gcf decode < payload.gcf
  gcf stats payload.json
"""


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE, end="")
        sys.exit(0 if args else 1)

    cmd = args[0]
    file_args = args[1:]

    if cmd == "encode":
        data = _read_input(file_args)
        _do_encode(data)
    elif cmd == "decode":
        data = _read_input(file_args)
        _do_decode(data)
    elif cmd == "stats":
        data = _read_input(file_args)
        _do_stats(data)
    elif cmd == "version":
        print("gcf 0.1.0")
    else:
        print(f"unknown command: {cmd}\n", file=sys.stderr)
        print(USAGE, file=sys.stderr, end="")
        sys.exit(1)


def _read_input(args: list[str]) -> str:
    if args and args[0] != "-":
        with open(args[0]) as f:
            return f.read()
    return sys.stdin.read()


def _payload_from_json(data: str) -> Payload:
    obj = json.loads(data)
    symbols = [
        Symbol(
            qualified_name=s["qualifiedName"],
            kind=s["kind"],
            score=s["score"],
            provenance=s["provenance"],
            distance=s.get("distance", 0),
        )
        for s in obj.get("symbols", [])
    ]
    edges = [
        Edge(
            source=e["source"],
            target=e["target"],
            edge_type=e["edgeType"],
            status=e.get("status", ""),
        )
        for e in obj.get("edges", [])
    ]
    return Payload(
        tool=obj.get("tool", ""),
        token_budget=obj.get("tokenBudget", 0),
        tokens_used=obj.get("tokensUsed", 0),
        pack_root=obj.get("packRoot", ""),
        symbols=symbols,
        edges=edges,
    )


def _payload_to_json(p: Payload) -> str:
    obj = {
        "tool": p.tool,
        "tokensUsed": p.tokens_used,
        "tokenBudget": p.token_budget,
        "packRoot": p.pack_root,
        "symbols": [
            {
                "qualifiedName": s.qualified_name,
                "kind": s.kind,
                "score": s.score,
                "provenance": s.provenance,
                "distance": s.distance,
            }
            for s in p.symbols
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "edgeType": e.edge_type,
                **({"status": e.status} if e.status else {}),
            }
            for e in p.edges
        ],
    }
    return json.dumps(obj, indent=2)


def _do_encode(data: str) -> None:
    try:
        p = _payload_from_json(data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    print(encode(p), end="")


def _do_decode(data: str) -> None:
    p = decode(data)
    print(_payload_to_json(p))


def _do_stats(data: str) -> None:
    try:
        p = _payload_from_json(data)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    gcf_output = encode(p)
    json_tokens = len(data.strip()) // 4
    gcf_tokens = len(gcf_output.strip()) // 4

    savings = 0.0
    if json_tokens > 0:
        savings = 100.0 * (1.0 - gcf_tokens / json_tokens)

    bar_width = 30
    json_bar = "█" * bar_width
    gcf_filled = (gcf_tokens * bar_width) // json_tokens if json_tokens > 0 else 0
    gcf_bar = "█" * gcf_filled + "░" * (bar_width - gcf_filled)

    print(f"Payload: {len(p.symbols)} symbols, {len(p.edges)} edges\n")
    print(f"  JSON  {json_bar}  {json_tokens} tokens")
    print(f"  GCF   {gcf_bar}  {gcf_tokens} tokens")
    print(f"\n  Savings: {savings:.0f}% fewer tokens with GCF")
