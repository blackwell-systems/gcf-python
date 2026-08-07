"""GCF keyed-tabular map encoding (SPEC 7.2a).

A JSON object whose values are all objects forming a losslessly-tabular set is
encoded as a keyed table `## [N:]{key,...}`: the shared value fields are declared
once in a header and each member is one positional row prefixed by its key. This
is the object-valued analogue of Section 7.4 tabular array encoding. It is
canonical (default-on): eligible maps always encode as keyed tables, with no
option to disable.
"""

from __future__ import annotations

from typing import Any


def keyed_map_eligible(m: Any) -> tuple[list[str], list[Any], list[str], str] | None:
    """Report whether an object is a keyed map of objects that should render as a
    keyed table `## [N:]{key,...}` (SPEC 7.2a.1). Returns the ordered member keys,
    the corresponding value objects, the ordered value-field union, and the
    key-column label, or None when the object is not eligible.
    """
    if not isinstance(m, dict):
        return None

    keys = list(m.keys())
    values = [m[k] for k in keys]

    # A keyed map requires at least two members: the form factors the shared value
    # fields into one header, which only pays off across multiple members. A
    # single-member map yields a one-row table the same size as a section, so keying
    # it would change canonical output for every nested single-member object (e.g.
    # `{"data": {...}}` wrappers) with no benefit. Single-member objects use ordinary
    # encoding; a single-key wrapper of a multi-member map therefore defers, and the
    # inner map is keyed at its own level (SPEC 7.2a.1).
    if len(keys) < 2:
        return None

    # Every value must be an object; build the ordered field union.
    seen: set[str] = set()
    value_fields: list[str] = []
    for v in values:
        if not isinstance(v, dict):
            return None  # non-object value
        for f in v:
            if f not in seen:
                seen.add(f)
                value_fields.append(f)
    if not value_fields:
        return None  # all-empty value objects

    # A keyed header needs at least one value field that can be a tabular column.
    # A field name containing ">" cannot be a column (SPEC 7.4.6.1.4); if every
    # value field contains ">", the keyed form would have only the key column,
    # which is invalid. Such a map uses Section 7.2 section encoding instead, the
    # object analogue of an array falling back to expanded form.
    if not any(">" not in f for f in value_fields):
        return None

    # Key-column label: "key", made unique by prepending "_" on collision.
    key_label = "key"
    while key_label in seen:
        key_label = "_" + key_label

    return keys, values, value_fields, key_label


def keyed_rows_to_map(rows: list[Any], fields: list[str]) -> dict[str, Any]:
    """Reconstruct the map from decoded keyed-table rows: the first declared field
    is the member key; the remaining fields form the value object (SPEC 7.2a.4).
    """
    if len(fields) < 2:
        raise ValueError("keyed_map: header must declare at least two fields")
    key_label = fields[0]
    out: dict[str, Any] = {}
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("keyed_map: row is not an object")
        if key_label not in r:
            raise ValueError(f"keyed_map: row missing key column {key_label!r}")
        kv = r[key_label]
        ks = kv if isinstance(kv, str) else str(kv)
        if ks in out:
            raise ValueError(f"keyed_map: duplicate member key {ks!r}")
        value = {k: v for k, v in r.items() if k != key_label}
        out[ks] = value
    return out
