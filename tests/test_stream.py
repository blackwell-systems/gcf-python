"""Tests for the StreamEncoder."""

import io

from gcf import StreamEncoder, Symbol, Edge, decode


def test_stream_basic():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "context_for_task", token_budget=5000)

    enc.write_symbol(Symbol(qualified_name="pkg.Auth", kind="function", score=0.78, provenance="lsp_resolved", distance=0))
    enc.write_symbol(Symbol(qualified_name="pkg.Server", kind="function", score=0.54, provenance="lsp_resolved", distance=1))
    enc.write_edge(Edge(source="pkg.Server", target="pkg.Auth", edge_type="calls"))
    enc.close()

    out = buf.getvalue()
    assert "GCF profile=graph tool=context_for_task budget=5000\n" in out
    assert "## targets\n" in out
    assert "@0 fn pkg.Auth 0.78 lsp_resolved\n" in out
    assert "## related\n" in out
    assert "@1 fn pkg.Server 0.54 lsp_resolved\n" in out
    assert "## edges [?]\n" in out
    assert "@0<@1 calls\n" in out
    assert "##! summary symbols=2 edges=1" in out

    # Header should not have symbols= or edges=
    header = out.split("\n")[0]
    assert "symbols=" not in header
    assert "edges=" not in header


def test_stream_round_trip():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "blast_radius", token_budget=10000)

    enc.write_symbol(Symbol(qualified_name="pkg.Auth", kind="function", score=0.95, provenance="lsp", distance=0))
    enc.write_symbol(Symbol(qualified_name="pkg.Config", kind="type", score=0.80, provenance="ast", distance=0))
    enc.write_symbol(Symbol(qualified_name="pkg.Server", kind="function", score=0.60, provenance="lsp", distance=1))
    enc.write_edge(Edge(source="pkg.Server", target="pkg.Auth", edge_type="calls"))
    enc.write_edge(Edge(source="pkg.Auth", target="pkg.Config", edge_type="references"))
    enc.close()

    p = decode(buf.getvalue())
    assert p.tool == "blast_radius"
    assert len(p.symbols) == 3
    assert len(p.edges) == 2


def test_stream_no_edges():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "test")

    enc.write_symbol(Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0))
    enc.close()

    out = buf.getvalue()
    assert "## edges" not in out
    assert "edges=0" in out


def test_stream_multiple_groups():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "test")

    enc.write_symbol(Symbol(qualified_name="a", kind="function", score=1.0, provenance="x", distance=0))
    enc.write_symbol(Symbol(qualified_name="b", kind="function", score=0.8, provenance="x", distance=1))
    enc.write_symbol(Symbol(qualified_name="c", kind="function", score=0.6, provenance="x", distance=2))
    enc.write_symbol(Symbol(qualified_name="d", kind="function", score=0.4, provenance="x", distance=5))
    enc.close()

    out = buf.getvalue()
    assert "## targets\n" in out
    assert "## related\n" in out
    assert "## extended\n" in out
    assert "## distance_5\n" in out
    assert "counts=1,1,1,1" in out


def test_stream_skips_unknown_refs():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "test")

    enc.write_symbol(Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0))
    enc.write_edge(Edge(source="unknown.B", target="a.A", edge_type="calls"))
    enc.close()

    out = buf.getvalue()
    assert "calls" not in out
    assert "edges=0" in out


def test_stream_incremental():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "test")

    # Header written immediately.
    assert buf.tell() > 0
    pos_after_header = buf.tell()

    enc.write_symbol(Symbol(qualified_name="a.A", kind="function", score=0.9, provenance="x", distance=0))
    assert buf.tell() > pos_after_header


def test_stream_bare_ref():
    buf = io.StringIO()
    enc = StreamEncoder(buf, "test", session=True)

    enc.write_bare_ref("pkg.Auth", 0)
    enc.write_symbol(Symbol(qualified_name="pkg.New", kind="function", score=0.85, provenance="lsp", distance=0))
    enc.close()

    out = buf.getvalue()
    assert "session=true" in out
    assert "@0  # previously transmitted" in out
    assert "@1 fn pkg.New 0.85 lsp" in out
