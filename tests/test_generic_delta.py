"""Unit tests for generic-profile delta (SPEC Section 10a). Mirrors gcf-go."""

import pytest

from gcf.generic_delta import (
    GenericDeltaPayload,
    GenericSet,
    _canonical_cell,
    decode_generic_delta,
    decode_generic_full,
    diff_generic_sets,
    encode_generic_delta,
    encode_generic_full,
    generic_pack_root,
    verify_generic_delta,
)


def orders_base():
    return GenericSet(key="id", name="orders", fields=["id", "total", "status", "customer"], rows=[
        {"id": 1001, "total": 59.98, "status": "shipped", "customer": "Alice"},
        {"id": 1002, "total": 29.99, "status": "pending", "customer": "Bob"},
        {"id": 1003, "total": 129.50, "status": "shipped", "customer": "Carol"},
    ])


def orders_next():
    return GenericSet(key="id", name="orders", fields=["id", "total", "status", "customer"], rows=[
        {"id": 1002, "total": 29.99, "status": "shipped", "customer": "Bob"},
        {"id": 1003, "total": 129.50, "status": "shipped", "customer": "Carol"},
        {"id": 1004, "total": 75.00, "status": "pending", "customer": "Dave"},
    ])


def test_roundtrip_by_root():
    base, nxt = orders_base(), orders_next()
    d = diff_generic_sets(base, nxt)
    assert (len(d.added), len(d.changed), len(d.removed)) == (1, 1, 1)
    assert d.new_root == generic_pack_root(nxt)
    result = verify_generic_delta(base, d, generic_pack_root(nxt))
    assert generic_pack_root(result) == generic_pack_root(nxt)


def test_pack_root_order_invariant():
    a = orders_base()
    b = orders_base()
    b.rows = [b.rows[2], b.rows[0], b.rows[1]]
    assert generic_pack_root(a) == generic_pack_root(b)


def test_canonical_cell_no_collision():
    assert _canonical_cell(None) == "-"
    assert _canonical_cell(True) == "true"
    assert _canonical_cell("true") == '"true"'
    assert _canonical_cell("-") == '"-"'
    assert _canonical_cell(59.98) == "59.98"
    assert _canonical_cell("59.98") == '"59.98"'
    assert _canonical_cell("a\tb") == '"a\\tb"'


def test_invariants():
    base = orders_base()
    base_root = generic_pack_root(base)

    dup = orders_base()
    dup.rows.append({"id": 1001, "total": 1.0, "status": "x", "customer": "y"})
    with pytest.raises(ValueError, match="duplicate identity"):
        diff_generic_sets(dup, orders_next())

    sc = orders_next()
    sc.fields = ["id", "total", "status"]
    with pytest.raises(ValueError, match="schema change"):
        diff_generic_sets(base, sc)

    add_existing = GenericDeltaPayload(key="id", fields=base.fields, base_root=base_root,
                                       added=[{"id": 1001, "total": 1.0, "status": "s", "customer": "c"}])
    with pytest.raises(ValueError, match="already exists"):
        verify_generic_delta(base, add_existing, "sha256:x")

    change_missing = GenericDeltaPayload(key="id", fields=base.fields, base_root=base_root,
                                         changed=[{"id": 9999, "total": 1.0, "status": "s", "customer": "c"}])
    with pytest.raises(ValueError, match="not in base"):
        verify_generic_delta(base, change_missing, "sha256:x")

    remove_missing = GenericDeltaPayload(key="id", fields=base.fields, base_root=base_root, removed=[9999])
    with pytest.raises(ValueError, match="not in base"):
        verify_generic_delta(base, remove_missing, "sha256:x")

    wrong_base = GenericDeltaPayload(key="id", fields=base.fields, base_root="sha256:wrong")
    with pytest.raises(ValueError, match="base_mismatch"):
        verify_generic_delta(base, wrong_base, base_root)

    d = diff_generic_sets(base, orders_next())
    with pytest.raises(ValueError, match="root_mismatch"):
        verify_generic_delta(base, d, "sha256:deadbeef")


def test_full_wire_roundtrip():
    base = orders_base()
    got, root = decode_generic_full(encode_generic_full(base, "orders_query"))
    assert generic_pack_root(got) == generic_pack_root(base)
    assert root == generic_pack_root(base)


def test_end_to_end():
    base, nxt = orders_base(), orders_next()
    held, _ = decode_generic_full(encode_generic_full(base, "orders_query"))
    d = diff_generic_sets(base, nxt)
    parsed = decode_generic_delta(encode_generic_delta(d))
    result = verify_generic_delta(held, parsed, generic_pack_root(nxt))
    assert generic_pack_root(result) == generic_pack_root(nxt)


def test_nulls_and_string_keys():
    nulls = GenericSet(key="id", name="items", fields=["id", "total", "status", "customer"], rows=[
        {"id": 2001, "total": 10.0, "status": None, "customer": "Amy"},
        {"id": 2002, "total": None, "status": "open", "customer": None},
    ])
    got, _ = decode_generic_full(encode_generic_full(nulls, ""))
    assert generic_pack_root(got) == generic_pack_root(nulls)

    sku = GenericSet(key="sku", name="parts", fields=["sku", "name", "qty"], rows=[
        {"sku": "1001", "name": "Widget", "qty": 5},  # "1001" spells a number -> quoted
        {"sku": "A-200", "name": "Gadget", "qty": 3},
    ])
    got2, _ = decode_generic_full(encode_generic_full(sku, ""))
    assert generic_pack_root(got2) == generic_pack_root(sku)


@pytest.mark.parametrize("wire", [
    "",
    "GCF profile=graph delta=true base_root=a new_root=b key=id\n",
    "GCF profile=generic pack_root=r key=id\n## t [1]{@id}\n1\n",  # not a delta
    "GCF profile=generic delta=true base_root=a new_root=b key=id\n## added [2]{@id,x}\n1|2\n",  # truncated
    "GCF profile=generic delta=true base_root=a new_root=b key=id\n## added [1]{@id,x}\n1\n",  # wrong cell count
    "GCF profile=generic delta=true base_root=a new_root=b key=id\n## bogus [1]{@id}\n1\n",  # unknown section
    "GCF profile=generic delta=true base_root=a new_root=b key=id\n## added [01]{@id,x}\n1|2\n",  # bad count
])
def test_decode_malformed_fails_closed(wire):
    with pytest.raises(Exception):
        decode_generic_delta(wire)
