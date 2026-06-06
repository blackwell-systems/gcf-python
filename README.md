<p align="center">
  <a href="https://github.com/blackwell-systems"><img src="https://raw.githubusercontent.com/blackwell-systems/blackwell-docs-theme/main/badge-trademark.svg" alt="Blackwell Systems"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
</p>

# gcf-python

Python implementation of [GCF (Graph Compact Format)](https://gcformat.com/) — the most token-efficient wire format for LLMs. A drop-in alternative to JSON and TOON for any structured data.

**79% fewer input tokens than JSON. 75% fewer output tokens. 52% smaller than TOON. 100% LLM comprehension at 500 symbols, where JSON scores 76.9% and TOON scores 92.3%.**

Docs: [gcformat.com](https://gcformat.com/) · [Playground](https://gcformat.com/playground.html) · [GCF vs TOON](https://gcformat.com/guide/vs-toon.html)

## Install

```
pip install gcf-python
```

Zero dependencies. Pure Python. Python 3.9+. Includes CLI. Don't want to change code? Use the [MCP proxy](https://github.com/blackwell-systems/gcf-proxy) for zero-code adoption.

## CLI

```bash
gcf encode < payload.json    # JSON to GCF
gcf decode < payload.gcf     # GCF to JSON
gcf stats  < payload.json    # token comparison with visual bar
```

```
Payload: 50 symbols, 20 edges

  JSON  ██████████████████████████████  4,200 tokens
  GCF   ████████░░░░░░░░░░░░░░░░░░░░░░  1,150 tokens

  Savings: 73% fewer tokens with GCF
```

## Library

### Quick Start

```python
from gcf import encode, Payload, Symbol, Edge

p = Payload(
    tool="context_for_task",
    token_budget=5000,
    tokens_used=1847,
    symbols=[
        Symbol(qualified_name="pkg.AuthMiddleware", kind="function", score=0.78, provenance="lsp_resolved", distance=0),
        Symbol(qualified_name="pkg.NewServer", kind="function", score=0.54, provenance="lsp_resolved", distance=1),
    ],
    edges=[
        Edge(source="pkg.NewServer", target="pkg.AuthMiddleware", edge_type="calls"),
    ],
)

output = encode(p)
```

Output:
```
GCF tool=context_for_task budget=5000 tokens=1847 symbols=2 edges=1
## targets
@0 fn pkg.AuthMiddleware 0.78 lsp_resolved
## related
@1 fn pkg.NewServer 0.54 lsp_resolved
## edges [1]
@0<@1 calls
```

## Decode

```python
from gcf import decode

p = decode(input_text)
print(p.tool, len(p.symbols), "symbols", len(p.edges), "edges")
```

## Session Deduplication

Track transmitted symbols across multiple tool responses. Previously-sent symbols become bare references instead of full declarations:

```python
from gcf import encode_with_session, Session, Payload, Symbol

sess = Session()

out1 = encode_with_session(payload1, sess)  # full declarations
out2 = encode_with_session(payload2, sess)  # reused symbols as "@N  # previously transmitted"
```

By the 5th call in a session: 92.7% token savings vs JSON.

## Streaming Encode

Write GCF output incrementally as symbols and edges arrive. Zero buffering, O(1) memory per row:

```python
from gcf import StreamEncoder, Symbol, Edge

enc = StreamEncoder(sys.stdout, "context_for_task", token_budget=5000)

enc.write_symbol(Symbol(qualified_name="pkg.Auth", kind="function", score=0.95, provenance="lsp", distance=0))
enc.write_symbol(Symbol(qualified_name="pkg.Server", kind="function", score=0.60, provenance="lsp", distance=1))
enc.write_edge(Edge(source="pkg.Server", target="pkg.Auth", edge_type="calls"))
enc.close()  # emits ## _summary trailer
```

Output:
```
GCF tool=context_for_task budget=5000
## targets
@0 fn pkg.Auth 0.95 lsp
## related
@1 fn pkg.Server 0.60 lsp
## edges [?]
@0<@1 calls
## _summary symbols=2 edges=1 sections=targets:1,related:1,edges:1
```

The writer is any object with a `write(s: str)` method. Thread-safe. Standard `decode()` handles streaming output with no changes.

## Delta Encoding

When the consumer already has a prior context pack, send only what changed:

```python
from gcf import encode_delta, DeltaPayload, Symbol, Edge

delta = DeltaPayload(
    tool="context_for_task",
    base_root="aaa111",
    new_root="bbb222",
    removed=[Symbol(qualified_name="pkg.OldFunc", kind="function")],
    added=[Symbol(qualified_name="pkg.NewFunc", kind="function", score=0.85, provenance="rwr")],
    delta_tokens=30,
    full_tokens=200,
)

output = encode_delta(delta)
```

81.2% savings on re-queries where the pack changed slightly.

## Generic Encoding

Encode any Python value (not just graph payloads) into GCF tabular format:

```python
from gcf import encode_generic

output = encode_generic({
    "employees": [
        {"id": 1, "name": "Alice", "department": "Engineering", "salary": 95000},
        {"id": 2, "name": "Bob", "department": "Sales", "salary": 72000},
    ],
})
```

Output:
```
## employees [2]{id,name,department,salary}
1|Alice|Engineering|95000
2|Bob|Sales|72000
```

Works on dicts, lists, and primitives. Lists of uniform dicts get tabular rows. Nested dicts use `## key` section headers.

## API

| Function | Description |
|----------|-------------|
| `encode(p: Payload) -> str` | Encode a graph payload to GCF text |
| `encode_generic(data: Any) -> str` | Encode any value to GCF tabular format |
| `decode(input_text: str) -> Payload` | Parse GCF text back to a Payload |
| `encode_with_session(p: Payload, s: Session) -> str` | Encode with session deduplication |
| `encode_delta(d: DeltaPayload) -> str` | Encode a delta (added/removed only) |
| `Session()` | Create a new session tracker (thread-safe) |

## Types

| Type | Purpose |
|------|---------|
| `Payload` | Full GCF payload: tool, budget, symbols, edges, pack root |
| `Symbol` | Graph node: qualified name, kind, score, provenance, distance |
| `Edge` | Directed relationship: source, target, edge type |
| `DeltaPayload` | Diff between two packs: added/removed symbols and edges |
| `Session` | Thread-safe tracker for multi-call deduplication |
| `KIND_ABBREV` / `KIND_EXPAND` | Bidirectional kind abbreviation dicts |

## Comprehension Eval

Rigorous 3-way benchmark (GCF vs TOON vs JSON) at 500 symbols, 200 edges. 13 structured extraction questions sent to an LLM with zero format instructions:

| Format | Accuracy | Tokens | vs JSON |
|--------|----------|--------|---------|
| **GCF** | **100%** (13/13) | **11,090** | **79% fewer** |
| TOON | 92.3% (12/13) | 16,378 | 69% fewer |
| JSON | 76.9% (10/13) | 53,341 | baseline |

GCF is the only format with perfect accuracy at scale, at 32% fewer tokens than TOON.

Reproduce: `git clone https://github.com/blackwell-systems/gcf-go && cd gcf-go/eval && GOWORK=off go test -run TestComprehension -v -timeout 0`

## Token Efficiency (TOON's Own Benchmark)

Running [TOON's benchmark harness](https://github.com/blackwell-systems/toon/tree/gcf-comparison) with GCF inserted (their datasets, their tokenizer):

| Track | GCF | TOON | Result |
|-------|-----|------|--------|
| Mixed-structure (nested, semi-uniform) | 170,367 | 227,896 | **GCF 34% smaller** |
| Flat-only (tabular) | 66,029 | 67,837 | **GCF 3% smaller** |
| Semi-uniform event logs | 108,158 | 154,032 | **GCF 42% smaller** |

GCF wins all 6 datasets. On semi-uniform data (the most common real-world pattern), GCF uses 42% fewer tokens than TOON.

Reproduce: `git clone https://github.com/blackwell-systems/toon && cd toon && git checkout gcf-comparison && cd benchmarks && pnpm install && pnpm benchmark:tokens`

## Links

- [Documentation](https://gcformat.com/)
- [Playground](https://gcformat.com/playground.html)
- [Specification](https://github.com/blackwell-systems/gcf)
- [Go library](https://github.com/blackwell-systems/gcf-go)
- [TypeScript library](https://github.com/blackwell-systems/gcf-typescript)
- [MCP Proxy](https://github.com/blackwell-systems/gcf-proxy) (zero-code adoption)
- [GCF vs TOON](https://gcformat.com/guide/vs-toon.html)
- [TOON benchmark fork](https://github.com/blackwell-systems/toon/tree/gcf-comparison)

## License

MIT
