"""Tests for GCF decoding."""

import pytest

from gcf import DecodeError, decode


def test_decode_basic_payload():
    """Decode a valid GCF payload with symbols and edges."""
    input_text = (
        "GCF tool=context_for_task budget=5000 tokens=1847 symbols=2\n"
        "## targets\n"
        "@0 fn pkg.AuthMiddleware 0.78 lsp_resolved\n"
        "## related\n"
        "@1 fn pkg.NewServer 0.54 lsp_resolved\n"
        "## edges\n"
        "@0<@1 calls\n"
    )

    p = decode(input_text)

    assert p.tool == "context_for_task"
    assert p.token_budget == 5000
    assert p.tokens_used == 1847
    assert len(p.symbols) == 2
    assert p.symbols[0].qualified_name == "pkg.AuthMiddleware"
    assert p.symbols[0].kind == "function"
    assert p.symbols[0].score == pytest.approx(0.78)
    assert p.symbols[0].provenance == "lsp_resolved"
    assert p.symbols[0].distance == 0
    assert p.symbols[1].qualified_name == "pkg.NewServer"
    assert p.symbols[1].distance == 1
    assert len(p.edges) == 1
    assert p.edges[0].source == "pkg.NewServer"
    assert p.edges[0].target == "pkg.AuthMiddleware"
    assert p.edges[0].edge_type == "calls"


def test_decode_with_pack_root():
    """Decode extracts pack_root from header."""
    input_text = "GCF tool=test budget=100 tokens=50 symbols=0 pack_root=abc123\n"
    p = decode(input_text)
    assert p.pack_root == "abc123"


def test_decode_kind_expansion():
    """Decode expands abbreviated kinds to full names."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=3\n"
        "## targets\n"
        "@0 iface pkg.Handler 0.90 lsp_resolved\n"
        "@1 route pkg.GetUsers 0.80 ast_inferred\n"
        "@2 ext github.com/lib.Func 0.70 ast_inferred\n"
    )
    p = decode(input_text)
    assert p.symbols[0].kind == "interface"
    assert p.symbols[1].kind == "route_handler"
    assert p.symbols[2].kind == "external"


def test_decode_unknown_kind_passthrough():
    """Unknown abbreviated kinds are kept as-is."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "## targets\n"
        "@0 custom pkg.X 0.50 test\n"
    )
    p = decode(input_text)
    assert p.symbols[0].kind == "custom"


def test_decode_distance_groups():
    """Decode assigns correct distance from group headers."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=3\n"
        "## targets\n"
        "@0 fn a.A 0.90 x\n"
        "## related\n"
        "@1 fn b.B 0.80 x\n"
        "## distance_5\n"
        "@2 fn c.C 0.70 x\n"
    )
    p = decode(input_text)
    assert p.symbols[0].distance == 0
    assert p.symbols[1].distance == 1
    assert p.symbols[2].distance == 5


def test_decode_edge_with_status():
    """Decode captures edge status field."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=2\n"
        "## targets\n"
        "@0 fn a.A 0.90 x\n"
        "@1 fn b.B 0.80 x\n"
        "## edges\n"
        "@0<@1 calls added\n"
    )
    p = decode(input_text)
    assert p.edges[0].status == "added"


def test_decode_ignores_comments():
    """Comments are skipped during parsing."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "# This is a comment\n"
        "## targets\n"
        "# Another comment\n"
        "@0 fn a.A 0.90 x\n"
    )
    p = decode(input_text)
    assert len(p.symbols) == 1


def test_decode_tolerates_crlf():
    """Decoder handles CRLF line endings."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\r\n"
        "## targets\r\n"
        "@0 fn a.A 0.90 x\r\n"
    )
    p = decode(input_text)
    assert len(p.symbols) == 1
    assert p.symbols[0].qualified_name == "a.A"


def test_decode_invalid_header():
    """Decode raises DecodeError for invalid header."""
    with pytest.raises(DecodeError, match="invalid header"):
        decode("INVALID header\n")


def test_decode_invalid_symbol_id():
    """Decode raises DecodeError for non-numeric symbol ID."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "## targets\n"
        "@abc fn a.A 0.90 x\n"
    )
    with pytest.raises(DecodeError, match="invalid symbol id"):
        decode(input_text)


def test_decode_invalid_score():
    """Decode raises DecodeError for non-numeric score."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "## targets\n"
        "@0 fn a.A notanumber x\n"
    )
    with pytest.raises(DecodeError, match="invalid score"):
        decode(input_text)


def test_decode_symbol_line_too_few_fields():
    """Decode raises DecodeError when symbol line has fewer than 5 fields."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "## targets\n"
        "@0 fn a.A\n"
    )
    with pytest.raises(DecodeError, match="at least 5 fields"):
        decode(input_text)


def test_decode_edge_missing_separator():
    """Decode raises DecodeError when edge line lacks < separator."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=2\n"
        "## targets\n"
        "@0 fn a.A 0.90 x\n"
        "@1 fn b.B 0.80 x\n"
        "## edges\n"
        "@0@1 calls\n"
    )
    with pytest.raises(DecodeError, match="missing '<' separator"):
        decode(input_text)


def test_decode_edge_unknown_symbol():
    """Decode raises DecodeError when edge references unknown symbol ID."""
    input_text = (
        "GCF tool=test budget=100 tokens=50 symbols=1\n"
        "## targets\n"
        "@0 fn a.A 0.90 x\n"
        "## edges\n"
        "@0<@99 calls\n"
    )
    with pytest.raises(DecodeError, match="unknown symbol id"):
        decode(input_text)
