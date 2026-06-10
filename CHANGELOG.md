# Changelog

## v1.0.0 (2026-06-10)

SPEC v2.0 implementation. 126/133 conformance fixtures passing (7 skipped: session, delta, binary UTF-8, negative zero, graph encode). 40M property-based round-trips with zero failures.

### Breaking changes from v0.5.0

- `encode_generic` emits `GCF profile=generic` header
- `decode_generic` requires `GCF profile=` header
- Strings colliding with typed literals are quoted
- Full JSON string escaping and number grammar
- `-` for null, `~` for absent, `^` for nested attachments
- `##! summary` trailer replaces `## _summary`
- Graph encoder emits `profile=graph`

### New

- `scalar.py`: common scalar grammar (quoting, escaping, parsing, number formatting)
- Conformance test runner (133 fixtures)
- Property-based round-trip tests (40M verified, configurable via `GCF_ITERATIONS`)

## v0.5.0 (2026-06-06)

- `GenericStreamEncoder`: zero-buffering tabular streaming encode (begin_array/write_row/end_array/write_kv/write_section/write_inline_array)
- `decode_generic`: decode any GCF text (tabular or graph) back to Python objects
- `StreamEncoder`: zero-buffering streaming encode (added in v0.4.0)

## v0.3.0 (2026-06-05)

- `encode_generic`: primitive arrays inlined as `name[N]: val1,val2,val3`

## v0.2.0 (2026-06-05)

- **Breaking**: `encode()` now emits `edges=N` in header line
- **Breaking**: `encode()` now emits `## edges [N]` section header (was `## edges`)
- `decode()` updated to parse `## edges [N]` format (strips bracket suffix)
- Session encoder updated to emit new edge count format

## v0.1.3 (2026-06-04)

- Docs: update README for PyPI discoverability (gcformat.com, proxy, vs-toon links)
- Fix: decoder rejects headers missing required `tool` field (conformance)
- Fix: escape newlines as `\n` in quoted strings in `encode_generic`

## v0.1.2 (2026-06-04)

- Fix: escape `"` inside quoted strings in `encode_generic`
- Fix: quote empty strings as `""` per spec

## v0.1.1 (2026-06-03)

- `encode_generic`: encode arbitrary Python values into GCF tabular format
- Tabular encoding: positional rows with pipe separators, section headers, nested field support
- Uniform array detection with 70% key overlap threshold

## v0.1.0 (2026-06-03)

- Initial release
- `encode` / `decode`: full GCF round-trip
- `encode_with_session`: session deduplication (92.7% savings by 5th call)
- `encode_delta`: delta encoding for re-queries (81.2% savings)
- Thread-safe `Session` class
- 16 kind abbreviations
- CLI: `gcf encode`, `gcf decode`, `gcf stats`
- Type hints, Python 3.9+, zero runtime dependencies
