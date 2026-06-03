"""Tests for GCF session deduplication."""

import threading

from gcf import Edge, Payload, Session, Symbol, encode_with_session


def test_session_first_encode_full_declarations():
    """First encode with session produces full declarations."""
    sess = Session()
    p = Payload(
        tool="context_for_task",
        token_budget=5000,
        tokens_used=1000,
        symbols=[
            Symbol(qualified_name="pkg.Func", kind="function", score=0.9, provenance="lsp_resolved", distance=0),
        ],
    )

    output = encode_with_session(p, sess)
    assert "session=true" in output
    assert "@0 fn pkg.Func 0.90 lsp_resolved" in output
    assert "previously transmitted" not in output


def test_session_second_encode_bare_refs():
    """Second encode with same session emits bare refs for known symbols."""
    sess = Session()
    p1 = Payload(
        tool="context_for_task",
        token_budget=5000,
        tokens_used=1000,
        symbols=[
            Symbol(qualified_name="pkg.Func", kind="function", score=0.9, provenance="lsp_resolved", distance=0),
            Symbol(qualified_name="pkg.Helper", kind="function", score=0.7, provenance="ast_inferred", distance=1),
        ],
    )

    # First encode: full declarations, records symbols.
    out1 = encode_with_session(p1, sess)
    assert "# previously transmitted" not in out1
    assert sess.size() == 2

    # Second encode with one known symbol and one new.
    p2 = Payload(
        tool="context_for_files",
        token_budget=3000,
        tokens_used=500,
        symbols=[
            Symbol(qualified_name="pkg.Func", kind="function", score=0.85, provenance="lsp_resolved", distance=0),
            Symbol(qualified_name="pkg.NewThing", kind="type", score=0.60, provenance="ast_inferred", distance=1),
        ],
        edges=[
            Edge(source="pkg.NewThing", target="pkg.Func", edge_type="calls"),
        ],
    )

    out2 = encode_with_session(p2, sess)
    assert "@0  # previously transmitted" in out2
    assert "@1 type pkg.NewThing 0.60 ast_inferred" in out2
    assert "## edges" in out2
    assert "@0<@1 calls" in out2
    assert sess.size() == 3  # Func, Helper, NewThing


def test_session_none_falls_back_to_encode():
    """encode_with_session with None session behaves like plain encode."""
    p = Payload(
        tool="test",
        token_budget=100,
        tokens_used=50,
        symbols=[
            Symbol(qualified_name="pkg.X", kind="function", score=0.5, provenance="test", distance=0),
        ],
    )
    output = encode_with_session(p, None)
    assert "session=true" not in output
    assert "@0 fn pkg.X 0.50 test" in output


def test_session_reset():
    """Reset clears session state."""
    sess = Session()
    sess.record([Symbol(qualified_name="pkg.X", kind="function", score=0.5, provenance="test")])
    assert sess.size() == 1
    sess.reset()
    assert sess.size() == 0
    assert not sess.transmitted("pkg.X")


def test_session_thread_safety():
    """Session is safe to use from multiple threads concurrently."""
    sess = Session()
    errors: list[Exception] = []

    def record_symbols(prefix: str):
        try:
            for i in range(100):
                sym = Symbol(
                    qualified_name=f"{prefix}.Func{i}",
                    kind="function",
                    score=0.5,
                    provenance="test",
                )
                sess.record([sym])
                # Interleave reads.
                sess.transmitted(f"{prefix}.Func{i}")
                sess.size()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=record_symbols, args=(f"pkg{t}",)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sess.size() == 1000  # 10 threads * 100 symbols


def test_session_get_id():
    """get_id returns correct ID for recorded symbols."""
    sess = Session()
    syms = [
        Symbol(qualified_name="a.A", kind="function", score=0.5, provenance="test"),
        Symbol(qualified_name="b.B", kind="function", score=0.5, provenance="test"),
    ]
    sess.record(syms)
    assert sess.get_id("a.A") == 0
    assert sess.get_id("b.B") == 1
    assert sess.get_id("c.C") == -1


def test_session_no_duplicate_recording():
    """Recording the same symbol twice does not create duplicate IDs."""
    sess = Session()
    sym = Symbol(qualified_name="pkg.X", kind="function", score=0.5, provenance="test")
    sess.record([sym])
    sess.record([sym])
    assert sess.size() == 1
    assert sess.get_id("pkg.X") == 0
