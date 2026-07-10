<p align="center">
  <a href="https://github.com/blackwell-systems"><img src="https://raw.githubusercontent.com/blackwell-systems/blackwell-docs-theme/main/badge-trademark.svg" alt="Blackwell Systems"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
</p>

# gcf-python

Python implementation of [GCF](https://gcformat.com/) — the most token-efficient wire format for LLMs. A drop-in alternative to JSON and TOON for any structured data.

**100% comprehension on every frontier model tested. 29% fewer tokens than TOON, 56% fewer than JSON across 16 datasets. 91.2% on structurally complex code graphs (vs TOON 68.8%, JSON 54.1%). 2,400+ LLM evaluations. Zero training.**

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

## Benchmarks

2,400+ LLM evaluations across 10 models, 3 providers, and 51 independent test runs.

| | GCF | TOON | JSON |
|---|---|---|---|
| **Comprehension** (23 runs, 10 models) | **91.2%** | 68.8% | 54.1% |
| **Generation** (28 runs, 9 models) | **5/5** | 1.0/5 | 5.0/5 |
| **Input tokens** (500 symbols) | **11,090** | 16,378 | 53,341 |
| **Output tokens** (100 symbols) | **5,976** | 8,937 | 16,121 |

GCF wins 15/16 datasets on the expanded [token efficiency benchmark](https://github.com/blackwell-systems/toon/tree/gcf-comparison). Full results: [gcformat.com/guide/benchmarks](https://gcformat.com/guide/benchmarks.html)

## Implementations

| Language | Package | Repository |
|----------|---------|-----------|
| Go | `go get github.com/blackwell-systems/gcf-go` | [gcf-go](https://github.com/blackwell-systems/gcf-go) |
| TypeScript | `npm install @blackwell-systems/gcf` | [gcf-typescript](https://github.com/blackwell-systems/gcf-typescript) |
| Python | `pip install gcf-python` | [gcf-python](https://github.com/blackwell-systems/gcf-python) |
| Rust | `cargo add gcf` | [gcf-rust](https://github.com/blackwell-systems/gcf-rust) |
| Swift | Swift Package Manager | [gcf-swift](https://github.com/blackwell-systems/gcf-swift) |
| Kotlin | JitPack | [gcf-kotlin](https://github.com/blackwell-systems/gcf-kotlin) |
| MCP Proxy | `pip install gcf-proxy` | [gcf-proxy](https://github.com/blackwell-systems/gcf-proxy) (bidirectional, session dedup, HTTP frontend) |
| Claude Code Plugin | `/plugin install` | [gcf-claude-plugin](https://github.com/blackwell-systems/gcf-claude-plugin) (one-command install, session stats hook) |
| Codex Plugin | `codex plugin add` | [gcf-codex-plugin](https://github.com/blackwell-systems/gcf-codex-plugin) (one-command install, session stats hook) |
| VS Code | `ext install blackwell-systems.gcf-vscode` | [gcf-vscode](https://marketplace.visualstudio.com/items?itemName=blackwell-systems.gcf-vscode) (syntax highlighting) |
| n8n | `npm install n8n-nodes-gcf` | [gcf-n8n-nodes](https://github.com/blackwell-systems/gcf-n8n-nodes) (workflow encode/decode) |
| Tree-sitter | `npm install tree-sitter-gcf` | [tree-sitter-gcf](https://github.com/blackwell-systems/tree-sitter-gcf) |

**Zero runtime dependencies. Permanently.** All six implementations depend only on their language's standard library. No transitive dependencies. No supply chain risk. This is a permanent commitment: GCF will never take on external runtime dependencies. MIT licensed. All implementations support both generic profile (`encodeGeneric`) and graph profile (`encode`). CLI included in all 6 languages.

**Specification:** [SPEC v3.2 Stable](https://github.com/blackwell-systems/gcf/blob/main/SPEC.md) with 174 conformance fixtures, 43,000,000,000+ lossless round-trips verified across 5 formats and 6 languages. All implementations at v2.2.1+ (Go v1.3.1). Cross-language 6x6 matrix verified.

## Adopted by

[Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp) (46K stars, Google Chrome DevTools team) · [Speakeasy](https://speakeasy.com) (API tooling, customers include Google, Verizon, Mistral AI, DocuSign, Vercel) · [OmniRoute](https://omniroute.online) (6.1K stars) · [NetClaw](https://github.com/automateyournetwork/netclaw) (556 stars) · [ctx](https://github.com/stevesolun/ctx) (510 stars) · [NeuroNest](https://neuronest.cc) · [Open Data Products SDK](https://opendataproducts.org/sdk/) (Linux Foundation) · [Raycast](https://raycast.com/blackwell-systems/json-to-gcf-converter) · [and more](https://gcformat.com/ecosystem/adopters.html)

## License

MIT - [Dayna Blackwell](https://github.com/blackwell-systems)
