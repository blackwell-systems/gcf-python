"""Tests for GCF encoding."""

from gcf import Edge, Payload, Symbol, encode


def test_encode_basic_payload():
    """Encode a payload with two symbols and one edge."""
    p = Payload(
        tool="context_for_task",
        token_budget=5000,
        tokens_used=1847,
        symbols=[
            Symbol(
                qualified_name="pkg.AuthMiddleware",
                kind="function",
                score=0.78,
                provenance="lsp_resolved",
                distance=0,
            ),
            Symbol(
                qualified_name="pkg.NewServer",
                kind="function",
                score=0.54,
                provenance="lsp_resolved",
                distance=1,
            ),
        ],
        edges=[
            Edge(source="pkg.NewServer", target="pkg.AuthMiddleware", edge_type="calls"),
        ],
    )

    output = encode(p)
    expected = (
        "GCF tool=context_for_task budget=5000 tokens=1847 symbols=2\n"
        "## targets\n"
        "@0 fn pkg.AuthMiddleware 0.78 lsp_resolved\n"
        "## related\n"
        "@1 fn pkg.NewServer 0.54 lsp_resolved\n"
        "## edges\n"
        "@0<@1 calls\n"
    )
    assert output == expected


def test_encode_with_pack_root():
    """Encode includes pack_root when set."""
    p = Payload(
        tool="context_for_files",
        token_budget=3000,
        tokens_used=500,
        pack_root="abc123def456",
        symbols=[
            Symbol(
                qualified_name="pkg.Handler",
                kind="function",
                score=0.90,
                provenance="ast_inferred",
                distance=0,
            ),
        ],
    )

    output = encode(p)
    assert "pack_root=abc123def456" in output


def test_encode_kind_abbreviations():
    """All standard kinds are abbreviated correctly."""
    kinds = {
        "function": "fn",
        "interface": "iface",
        "route_handler": "route",
        "external": "ext",
        "package": "pkg",
        "service": "svc",
    }
    for full, abbrev in kinds.items():
        p = Payload(
            tool="test",
            symbols=[
                Symbol(
                    qualified_name="pkg.X",
                    kind=full,
                    score=0.5,
                    provenance="test",
                    distance=0,
                ),
            ],
        )
        output = encode(p)
        assert f"@0 {abbrev} pkg.X" in output


def test_encode_unknown_kind_passthrough():
    """Unknown kinds are passed through verbatim."""
    p = Payload(
        tool="test",
        symbols=[
            Symbol(
                qualified_name="pkg.X",
                kind="custom_kind",
                score=0.5,
                provenance="test",
                distance=0,
            ),
        ],
    )
    output = encode(p)
    assert "@0 custom_kind pkg.X" in output


def test_encode_distance_groups():
    """Symbols are grouped by distance with correct headers."""
    p = Payload(
        tool="test",
        token_budget=1000,
        tokens_used=500,
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
            Symbol(qualified_name="b.B", kind="function", score=0.8, provenance="x", distance=1),
            Symbol(qualified_name="c.C", kind="function", score=0.7, provenance="x", distance=2),
            Symbol(qualified_name="d.D", kind="function", score=0.6, provenance="x", distance=5),
        ],
    )
    output = encode(p)
    assert "## targets\n" in output
    assert "## related\n" in output
    assert "## extended\n" in output
    assert "## distance_5\n" in output


def test_encode_edge_with_status():
    """Edge status is appended when not empty or unchanged."""
    p = Payload(
        tool="test",
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
            Symbol(qualified_name="b.B", kind="function", score=0.8, provenance="x", distance=0),
        ],
        edges=[
            Edge(source="b.B", target="a.A", edge_type="calls", status="added"),
        ],
    )
    output = encode(p)
    assert "@0<@1 calls added\n" in output


def test_encode_edge_unchanged_status_omitted():
    """Edge with status 'unchanged' omits the status field."""
    p = Payload(
        tool="test",
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
            Symbol(qualified_name="b.B", kind="function", score=0.8, provenance="x", distance=0),
        ],
        edges=[
            Edge(source="b.B", target="a.A", edge_type="calls", status="unchanged"),
        ],
    )
    output = encode(p)
    assert "@0<@1 calls\n" in output


def test_encode_skips_edges_with_missing_symbols():
    """Edges referencing unknown symbols are skipped, but section header emitted."""
    p = Payload(
        tool="test",
        symbols=[
            Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0),
        ],
        edges=[
            Edge(source="nonexistent.B", target="a.A", edge_type="calls"),
        ],
    )
    output = encode(p)
    # Section header is emitted (matches Go), but no edge lines beneath it
    assert "## edges" in output
    lines_after_edges = output.split("## edges\n")[1]
    assert lines_after_edges.strip() == ""


def test_encode_empty_payload():
    """Empty payload produces only header."""
    p = Payload(tool="test", token_budget=100, tokens_used=0)
    output = encode(p)
    assert output == "GCF tool=test budget=100 tokens=0 symbols=0\n"
