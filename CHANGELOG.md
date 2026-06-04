# Changelog

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
