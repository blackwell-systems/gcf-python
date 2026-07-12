# Changelog

## v2.3.0 (unreleased)

### Generic-profile delta encoding (SPEC §10a)

- Full producer + consumer implementation of generic-profile delta, byte-for-byte interoperable with `gcf-go`:
  - `GenericSet` (keyed record set), `GenericDeltaPayload`
  - `generic_pack_root` (`gcf-pack-root-v1`, generic profile) with a purpose-built cell canonicalization decoupled from the wire cell encoder: collision-free (null/bool/number bare, strings always quoted) and record-safe. Fields and records sort by UTF-8 byte order to match Go's `sort.Strings`.
  - `diff_generic_sets` (the blessed producer path; centralizes the keyed-diff invariants), `encode_generic_full`, `encode_generic_delta`
  - `decode_generic_full`, `decode_generic_delta` (consumer wire parsing)
  - `verify_generic_delta` (atomic apply + `new_root` verification)
- Delta is opt-in and bilateral; the existing `encode_generic` path is unchanged (backward compatible).

### Tests

- Unit suite mirroring `gcf-go`: self-proving round-trip (diff -> encode -> apply -> recomputed root), determinism / row-order invariance, no-type-collision canonicalization, every invariant/error path, full-payload wire round-trip, the complete server -> wire -> consumer end-to-end loop, and malformed-wire-fails-closed.
- Conformance runner support for `generic-pack-root`, `generic-delta`, `generic-delta-verify`, `generic-delta-decode` (12 shared fixtures); verified to produce identical pack roots and delta wire to `gcf-go`.

## v2.2.2 (2026-07-10)

### Fixes

- **Losslessness (nested null):** a nested object that is null at an intermediate level (e.g. `{"meta": {"owner": None}}`) is no longer flattened. Previously its leaves encoded as absent (`~`) and unflattened to a missing key, silently dropping the null. Such fields now fall back to the attachment mechanism; a top-level `None` still flattens losslessly (emits `-`, reconstructs via the all-null rule). Enforced by the shared conformance fixtures `flatten/017`–`019`. Prototype pollution does not affect Python (dicts have no mutable prototype).

### Tests

- `test_flatten_roundtrip`: aligned arrays whose shared fields are fixed-shape nested objects with a field or an intermediate nested level sometimes null/absent — the shape the prior scalar-only generator never produced, leaving the flatten/unflatten path unexercised. Verified to fail on the pre-fix encoder and pass on the fix.

## v2.2.1 (2026-06-23)

### Flatten Opt-Out

- Added `GenericOptions` dataclass with `no_flatten` field to disable nested object flattening
- `encode_generic(data, GenericOptions(no_flatten=True))` produces attachment syntax instead of path columns
- Backward compatible: `encode_generic(data)` behavior unchanged (flatten on by default)
- Fixed: field names containing `>` no longer appear as tabular columns (spec rule 7.4.6.1.4)
- Fixed: field names containing `>` no longer eligible for flattening analysis
- Fixed: decoder no longer treats literal `>` in key names as a path separator
- Fixed: decoder accepts orphan attachments (fields excluded from column list)
- 12 targeted edge case tests for `>` in field names

## v2.2.0 (2026-06-22)

### Spec v3.2: Nested Object Flattening

- Encoder automatically flattens fixed-shape nested objects into `>` path column names (e.g., `"customer>name"` instead of `^` + `.customer {}` attachment)
- Decoder reconstructs nested objects from `>` path columns
- 20-48% fewer tokens on deeply nested API data (Jira, Stripe, K8s, calendar events)
- 100% comprehension on every frontier model (validated across 9 models, 7 providers)
- Zero regression on lossless round-trips (230 tests, conformance + property-based)
- Falls back to attachment mechanism for: variable-length arrays, objects with different keys across rows, objects with `>` in key names, empty nested objects

## v2.1.0 (2026-06-14)

### Spec v3.1

- `tool` field in graph profile header is now optional (SHOULD be present for MCP, not required)

### Bug Fixes

- Quote strings containing commas (conformance: `inline-schema/006_inline_with_quoted_values`)
- Decode v2-format indented attachments in tabular rows (conformance: `decode/002_attachment`)
- Reject duplicate attachments on the same row (conformance: `errors-v2/027_duplicate_attachment`)

## v2.0.0 (2026-06-12)

### Breaking Changes

- `encode_generic` now produces inline schema format (not backwards compatible with v1.x decoders)
- Attachment lines no longer indented (same depth as parent row)
- Inline object fields use positional encoding without field-name prefix

### New Features

- Inline object schema: objects with 3+ scalar fields encoded positionally with `^{fields}` header
- Shared array schemas: identical nested arrays omit `{fields}` after first row
- 472M+ fuzz iterations across all 6 implementations, zero failures

### Bug Fixes

- Quote strings starting with `.` (dot prefix)
- Quote C1 control characters (U+0080-U+009F)
- Quote Unicode whitespace (NBSP, hair space, etc.)

## v1.0.1 (2026-06-10)

- CLI: `encode-generic` and `decode-generic` subcommands for generic profile
- CLI now supports both graph and generic profiles
- `python -m gcf` entry point

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
