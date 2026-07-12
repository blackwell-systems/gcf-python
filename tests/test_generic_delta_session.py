"""Unit tests for GenericDeltaSession (SPEC Section 10a.8).

Mirrors gcf-go's generic_delta_session_test.go: cadence patterns under both
policies, schema-change forcing a full, the FixedN(15)-over-30-turns count, and
the load-bearing consumer-stays-in-sync check.
"""

from __future__ import annotations

import pytest

from gcf.generic_delta import (
    GenericDeltaSession,
    GenericSet,
    decode_generic_delta,
    decode_generic_full,
    fixed_n,
    generic_pack_root,
    size_guard,
    verify_generic_delta,
)


# --- scenario builders ---


def sess_base() -> GenericSet:
    return GenericSet(
        name="orders",
        key="id",
        fields=["id", "total", "status", "customer"],
        rows=[
            {"id": 1001.0, "total": 59.98, "status": "shipped", "customer": "Alice"},
            {"id": 1002.0, "total": 29.99, "status": "pending", "customer": "Bob"},
            {"id": 1003.0, "total": 129.50, "status": "shipped", "customer": "Carol"},
        ],
    )


def _mk(*rows: dict) -> GenericSet:
    return GenericSet(
        name="orders", key="id", fields=["id", "total", "status", "customer"], rows=list(rows)
    )


def sess_updates() -> list[GenericSet]:
    return [
        _mk(
            {"id": 1001.0, "total": 59.98, "status": "shipped", "customer": "Alice"},
            {"id": 1002.0, "total": 29.99, "status": "shipped", "customer": "Bob"},  # changed
            {"id": 1003.0, "total": 129.50, "status": "shipped", "customer": "Carol"},
        ),
        _mk(  # add 1004
            {"id": 1001.0, "total": 59.98, "status": "shipped", "customer": "Alice"},
            {"id": 1002.0, "total": 29.99, "status": "shipped", "customer": "Bob"},
            {"id": 1003.0, "total": 129.50, "status": "shipped", "customer": "Carol"},
            {"id": 1004.0, "total": 75.00, "status": "pending", "customer": "Dave"},
        ),
        _mk(  # remove 1001
            {"id": 1002.0, "total": 29.99, "status": "shipped", "customer": "Bob"},
            {"id": 1003.0, "total": 129.50, "status": "shipped", "customer": "Carol"},
            {"id": 1004.0, "total": 75.00, "status": "pending", "customer": "Dave"},
        ),
        _mk(  # change 1003
            {"id": 1002.0, "total": 29.99, "status": "shipped", "customer": "Bob"},
            {"id": 1003.0, "total": 140.00, "status": "delivered", "customer": "Carol"},
            {"id": 1004.0, "total": 75.00, "status": "pending", "customer": "Dave"},
        ),
        _mk(  # add 1005
            {"id": 1002.0, "total": 29.99, "status": "shipped", "customer": "Bob"},
            {"id": 1003.0, "total": 140.00, "status": "delivered", "customer": "Carol"},
            {"id": 1004.0, "total": 75.00, "status": "pending", "customer": "Dave"},
            {"id": 1005.0, "total": 12.00, "status": "pending", "customer": "Eve"},
        ),
    ]


_NAMES = [
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Heidi",
    "Ivan", "Judy", "Mallory", "Niaj", "Olivia", "Peggy", "Rupert", "Sybil",
    "Trent", "Uma", "Victor", "Walter",
]


def size_guard_base() -> GenericSet:
    rows = [
        {"id": float(2000 + i), "total": float(10 + i), "status": "pending", "customer": n}
        for i, n in enumerate(_NAMES)
    ]
    return GenericSet(name="rows", key="id", fields=["id", "total", "status", "customer"], rows=rows)


def size_guard_updates() -> list[GenericSet]:
    base = size_guard_base()

    def clone() -> GenericSet:
        rows = [dict(r) for r in base.rows]
        return GenericSet(name=base.name, key=base.key, fields=list(base.fields), rows=rows)

    ups: list[GenericSet] = []
    for turn in range(6):
        g = clone()
        g.rows[turn]["status"] = "shipped"  # change one distinct row's status each turn
        ups.append(g)
    return ups


# --- unit tests ---


def test_session_fixed_n_pattern():
    s = GenericDeltaSession(sess_base(), "orders_query", fixed_n(3))
    want_full = [False, False, True, False, False]  # re-anchor on turn 3
    for i, up in enumerate(sess_updates()):
        _, is_full = s.next(up)
        assert is_full == want_full[i], f"turn {i + 1}: isFull={is_full}, want {want_full[i]}"


def test_session_size_guard_triggers():
    s = GenericDeltaSession(size_guard_base(), "", size_guard())
    anchors = 0
    for up in size_guard_updates():
        _, is_full = s.next(up)
        if is_full:
            anchors += 1
    assert anchors >= 1, "SizeGuard never re-anchored across 6 turns; scenario should trigger at least one"


def test_session_schema_change_reanchors():
    s = GenericDeltaSession(sess_base(), "orders_query", fixed_n(15))
    changed = sess_base()
    changed.fields = ["id", "total", "status"]  # drop a column
    changed.rows = [{"id": 1001.0, "total": 59.98, "status": "shipped"}]
    _, is_full = s.next(changed)
    assert is_full, "schema change must force a full re-anchor"


def test_session_fixed_n_15_over_30_turns():
    """N=15 over 30 update turns -> exactly two fulls (turns 15 and 30), 28 deltas."""
    s = GenericDeltaSession(sess_base(), "orders_query", fixed_n(15))
    _ = s.current_full()  # bootstrap full (turn 0), not counted below

    fulls, deltas = 0, 0
    full_turns: list[int] = []
    prev = sess_base()
    for turn in range(1, 31):
        rows = []
        for j, r in enumerate(prev.rows):
            nr = dict(r)
            if j == turn % len(prev.rows):
                nr["total"] = float(turn) + 0.5
            rows.append(nr)
        nxt = GenericSet(name=prev.name, key=prev.key, fields=list(prev.fields), rows=rows)
        _, is_full = s.next(nxt)
        if is_full:
            fulls += 1
            full_turns.append(turn)
        else:
            deltas += 1
        prev = nxt

    assert (fulls, deltas) == (2, 28), f"over 30 turns: got {fulls} fulls / {deltas} deltas, want 2 / 28"
    assert full_turns == [15, 30], f"full re-anchors at turns {full_turns}, want [15, 30]"


@pytest.mark.parametrize(
    "base,ups,tool,policy",
    [
        (sess_base(), sess_updates(), "orders_query", fixed_n(3)),
        (size_guard_base(), size_guard_updates(), "", size_guard()),
    ],
    ids=["fixedN3", "sizeGuard"],
)
def test_session_consumer_stays_in_sync(base, ups, tool, policy):
    """A consumer applying each emission stays byte-for-byte in sync every turn."""
    s = GenericDeltaSession(base, tool, policy)
    held, _ = decode_generic_full(s.current_full())
    for i, up in enumerate(ups):
        wire, is_full = s.next(up)
        if is_full:
            held, _ = decode_generic_full(wire)
        else:
            d = decode_generic_delta(wire)
            held = verify_generic_delta(held, d, d.new_root)
        assert generic_pack_root(held) == generic_pack_root(up), (
            f"turn {i + 1}: consumer root != producer root (isFull={is_full})"
        )
