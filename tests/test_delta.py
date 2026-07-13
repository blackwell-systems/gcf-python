"""Tests for GCF delta encoding."""

from gcf import DeltaPayload, Edge, Symbol, encode_delta


def test_encode_delta_basic():
    """Encode a delta payload with removed and added symbols."""
    d = DeltaPayload(
        tool="context_for_task",
        base_root="aaa111",
        new_root="bbb222",
        removed=[
            Symbol(qualified_name="pkg.OldHandler", kind="function"),
        ],
        added=[
            Symbol(qualified_name="pkg.NewHandler", kind="function", score=0.85, provenance="rwr"),
        ],
        removed_edges=[
            Edge(source="pkg.Router", target="pkg.OldHandler", edge_type="calls"),
        ],
        added_edges=[
            Edge(source="pkg.Router", target="pkg.NewHandler", edge_type="calls"),
        ],
        delta_tokens=30,
        full_tokens=200,
    )

    output = encode_delta(d)

    assert "delta=true" in output
    assert "base_root=aaa111" in output
    assert "new_root=bbb222" in output
    assert "tokens=30" in output
    assert "savings=85%" in output
    assert "## removed\n" in output
    assert "fn pkg.OldHandler\n" in output
    assert "## added\n" in output
    assert "@0 fn pkg.NewHandler 0.85 rwr 0\n" in output
    assert "## edges_removed\n" in output
    assert "pkg.Router -> pkg.OldHandler calls\n" in output
    assert "## edges_added\n" in output
    assert "pkg.Router -> pkg.NewHandler calls\n" in output


def test_encode_delta_savings_calculation():
    """Savings percentage is calculated correctly."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        added=[
            Symbol(qualified_name="pkg.X", kind="type", score=0.5, provenance="test"),
        ],
        delta_tokens=20,
        full_tokens=100,
    )
    output = encode_delta(d)
    assert "savings=80%" in output


def test_encode_delta_zero_full_tokens():
    """Zero full_tokens yields 0% savings (no division by zero)."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        delta_tokens=10,
        full_tokens=0,
    )
    output = encode_delta(d)
    assert "savings=0%" in output


def test_encode_delta_only_removed():
    """Delta with only removed symbols omits added sections."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        removed=[
            Symbol(qualified_name="pkg.Gone", kind="method"),
        ],
        delta_tokens=5,
        full_tokens=50,
    )
    output = encode_delta(d)
    assert "## removed\n" in output
    assert "method pkg.Gone\n" in output
    assert "## added" not in output
    assert "## edges_removed" not in output
    assert "## edges_added" not in output


def test_encode_delta_only_added():
    """Delta with only added symbols omits removed sections."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        added=[
            Symbol(qualified_name="pkg.New", kind="class", score=0.75, provenance="lsp_resolved"),
        ],
        delta_tokens=15,
        full_tokens=100,
    )
    output = encode_delta(d)
    assert "## added\n" in output
    assert "@0 class pkg.New 0.75 lsp_resolved 0\n" in output
    assert "## removed" not in output


def test_encode_delta_multiple_added_sequential_ids():
    """Multiple added symbols get sequential IDs starting from 0."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        added=[
            Symbol(qualified_name="pkg.A", kind="function", score=0.9, provenance="x"),
            Symbol(qualified_name="pkg.B", kind="function", score=0.8, provenance="x"),
            Symbol(qualified_name="pkg.C", kind="function", score=0.7, provenance="x"),
        ],
        delta_tokens=40,
        full_tokens=200,
    )
    output = encode_delta(d)
    assert "@0 fn pkg.A 0.90 x 0\n" in output
    assert "@1 fn pkg.B 0.80 x 0\n" in output
    assert "@2 fn pkg.C 0.70 x 0\n" in output


def test_encode_delta_kind_abbreviation():
    """Delta encoding uses kind abbreviations."""
    d = DeltaPayload(
        tool="test",
        base_root="x",
        new_root="y",
        removed=[
            Symbol(qualified_name="pkg.X", kind="interface"),
        ],
        added=[
            Symbol(qualified_name="pkg.Y", kind="route_handler", score=0.5, provenance="test"),
        ],
        delta_tokens=10,
        full_tokens=100,
    )
    output = encode_delta(d)
    assert "iface pkg.X\n" in output
    assert "route pkg.Y" in output
