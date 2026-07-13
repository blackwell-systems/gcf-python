"""Tests for GCF encode/decode round-trip integrity."""

import pytest

from gcf import Edge, Payload, Symbol, decode, encode


def test_roundtrip_basic():
    """Encode then decode produces equivalent payload."""
    original = Payload(
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

    encoded = encode(original)
    decoded = decode(encoded)

    assert decoded.tool == original.tool
    assert decoded.token_budget == original.token_budget
    assert decoded.tokens_used == original.tokens_used
    assert len(decoded.symbols) == len(original.symbols)
    for orig, dec in zip(original.symbols, decoded.symbols):
        assert dec.qualified_name == orig.qualified_name
        assert dec.kind == orig.kind
        assert dec.score == pytest.approx(orig.score, abs=0.005)
        assert dec.provenance == orig.provenance
        assert dec.distance == orig.distance
    assert len(decoded.edges) == len(original.edges)
    for orig, dec in zip(original.edges, decoded.edges):
        assert dec.source == orig.source
        assert dec.target == orig.target
        assert dec.edge_type == orig.edge_type


def test_roundtrip_with_pack_root():
    """Pack root survives round-trip."""
    original = Payload(
        tool="test",
        token_budget=1000,
        tokens_used=200,
        pack_root="deadbeef01234567",
        symbols=[
            Symbol(qualified_name="pkg.X", kind="type", score=0.65, provenance="rwr", distance=0),
        ],
    )

    decoded = decode(encode(original))
    assert decoded.pack_root == "deadbeef01234567"


def test_roundtrip_all_kinds():
    """All standard kinds survive round-trip through abbreviation/expansion."""
    kinds = [
        "function", "type", "method", "interface", "var", "const",
        "resource", "table", "class", "selector", "field",
        "route_handler", "external", "file", "package", "service",
    ]
    symbols = [
        Symbol(
            qualified_name=f"pkg.Symbol{i}",
            kind=kind,
            score=round(0.9 - i * 0.01, 2),
            provenance="test",
            distance=0,
        )
        for i, kind in enumerate(kinds)
    ]
    original = Payload(tool="test", token_budget=1000, tokens_used=500, symbols=symbols)

    decoded = decode(encode(original))
    for orig, dec in zip(original.symbols, decoded.symbols):
        assert dec.kind == orig.kind, f"Kind mismatch for {orig.qualified_name}: {dec.kind} != {orig.kind}"


def test_roundtrip_multiple_distance_groups():
    """Multiple distance groups survive round-trip."""
    original = Payload(
        tool="test",
        token_budget=1000,
        tokens_used=500,
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
            Symbol(qualified_name="b.B", kind="function", score=0.8, provenance="x", distance=1),
            Symbol(qualified_name="c.C", kind="function", score=0.7, provenance="x", distance=2),
            Symbol(qualified_name="d.D", kind="function", score=0.6, provenance="x", distance=7),
        ],
    )

    decoded = decode(encode(original))
    for orig, dec in zip(original.symbols, decoded.symbols):
        assert dec.distance == orig.distance


def test_roundtrip_multiple_edges():
    """Multiple edges with different types survive round-trip."""
    original = Payload(
        tool="test",
        token_budget=1000,
        tokens_used=500,
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
            Symbol(qualified_name="b.B", kind="type", score=0.8, provenance="x", distance=0),
            Symbol(qualified_name="c.C", kind="method", score=0.7, provenance="x", distance=1),
        ],
        edges=[
            Edge(source="c.C", target="a.A", edge_type="calls"),
            Edge(source="c.C", target="b.B", edge_type="implements"),
            Edge(source="a.A", target="b.B", edge_type="returns"),
        ],
    )

    decoded = decode(encode(original))
    assert len(decoded.edges) == 3
    # The encoder orders edges by source ID, then target ID, then edge type
    # (SPEC 16.1), so compare as a set rather than by input order.
    orig_set = {(e.source, e.target, e.edge_type) for e in original.edges}
    dec_set = {(e.source, e.target, e.edge_type) for e in decoded.edges}
    assert dec_set == orig_set


def test_roundtrip_empty_payload():
    """Empty payload (no symbols, no edges) round-trips cleanly."""
    original = Payload(tool="empty", token_budget=0, tokens_used=0)
    decoded = decode(encode(original))
    assert decoded.tool == "empty"
    assert decoded.symbols == []
    assert decoded.edges == []
