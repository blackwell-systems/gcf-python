"""Property-based round-trip fuzz for the keyed-tabular map encoding (SPEC 7.2a).

Covers both encode paths:
- buffered: encode_generic() routing a map-of-objects to a keyed table [N:], at
  root, named-nested, expanded-item, and tabular-row-attachment positions;
- streaming: GenericStreamEncoder.begin_keyed_map() emitting [?:] with a fixed
  value schema.

Every generated case decodes the raw encoder output with no workarounds: a needed
workaround would be a bug. Also asserts the selection rule (SPEC 7.2a.1): a
single-member map is NOT keyed; a map whose value fields all contain '>' falls
back to section encoding; a map with all-empty value objects falls back too.
"""

import io
import json
import math
import os
import random
import string

import pytest

from gcf import encode_generic, decode_generic, GenericStreamEncoder

ITERATIONS = int(os.environ.get("GCF_KEYED_ITERATIONS", "60000"))

# Adversarial alphabets mirroring the v2 round-trip suite: strings and keys that
# collide with GCF markers and delimiters, stressing cell/field quoting.
SPECIAL = ' |,="\\#@\n\t~^+-.>'
BARE = string.ascii_letters + string.digits

COLLISION_STRINGS = [
    "true", "false", "-", "~", "^",
    "0", "1", "42", "-1", "3.14", "1e10", "-0",
    "", " ", "  ", " x", "x ",
    "#", "# comment", "@0", "@handle",
    "+1", ".5", "+.3", "01", "00",
    "null", "NULL", "True", "False",
    "|", ",", "=", '"', "\\",
    "\n", "\r", "\t", "\b",
    "a|b", "a,b", "a=b", "hello world",
]


def _gen_number(r):
    return r.choice([
        lambda: 0,
        lambda: r.randint(0, 999),
        lambda: -r.randint(0, 999),
        lambda: r.randint(0, 999999) + r.random(),
        lambda: (r.randint(1, 999)) * 1e18,
        lambda: (r.randint(1, 999)) * 1e-10,
    ])()


def _gen_string(r):
    n = r.randint(0, 19)
    return "".join(
        r.choice(SPECIAL) if r.random() < 0.2 else r.choice(BARE) for _ in range(n)
    )


def _gen_bare_key(r):
    chars = string.ascii_lowercase + "_"
    return "".join(r.choice(chars) for _ in range(1 + r.randint(0, 7)))


def _gen_scalar(r):
    if r.random() < 0.25:
        return r.choice(COLLISION_STRINGS)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
    ])()


def _norm(v):
    return json.loads(json.dumps(v))


def _deep_equal(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or (math.isnan(a) if isinstance(a, float) else False)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b


def _gen_key(r):
    """An adversarial member key or value-field name: collision strings, special
    characters, or a bare key. Cell 0 (the key) and field names both stress
    quoting."""
    if r.random() < 0.3:
        return r.choice(COLLISION_STRINGS)
    if r.random() < 0.3:
        return _gen_string(r)
    return _gen_bare_key(r)


def _gen_value_fields(r, allow_gt):
    """A distinct, non-empty set of value-field names."""
    nf = 1 + r.randint(0, 4)
    fields = []
    seen = set()
    guard = 0
    while len(fields) < nf and guard < 100:
        guard += 1
        f = _gen_key(r)
        if not allow_gt and ">" in f:
            continue
        if f == "" or f in seen:
            continue
        seen.add(f)
        fields.append(f)
    return fields


def _gen_member_keys(r, n):
    keys = []
    seen = set()
    guard = 0
    while len(keys) < n and guard < 200:
        guard += 1
        k = _gen_key(r)
        if k in seen:
            continue
        seen.add(k)
        keys.append(k)
    return keys


def _gen_keyed_map(r, allow_gt=True):
    """A map with >=2 members, every value a non-empty object over a shared-ish
    (semi-uniform) field set. Some rows omit some fields (absent) or set null."""
    fields = _gen_value_fields(r, allow_gt)
    if not fields:
        fields = ["a"]
    n = 2 + r.randint(0, 6)
    keys = _gen_member_keys(r, n)
    if len(keys) < 2:
        return None
    m = {}
    for k in keys:
        obj = {}
        for f in fields:
            c = r.randint(0, 3)
            if c == 0:
                continue  # absent
            elif c == 1:
                obj[f] = None
            else:
                obj[f] = _gen_scalar(r)
        # Every value object must be non-empty for keyed eligibility; if this row
        # ended up empty, force at least one field.
        if not obj:
            obj[fields[0]] = _gen_scalar(r)
        m[k] = obj
    return m


def test_buffered_keyed_map_round_trip():
    r = random.Random(0x7EA5)
    keyed_seen = 0
    for i in range(ITERATIONS):
        m = _gen_keyed_map(r)
        if m is None:
            continue
        wire = encode_generic(m)
        # A map of >=2 non-empty objects with at least one non-'>' field must key.
        if "[" in wire and ":]" in wire.split("\n", 2)[1]:
            keyed_seen += 1
        decoded = decode_generic(wire)
        assert _deep_equal(_norm(m), _norm(decoded)), (
            f"iter {i}: round-trip mismatch\n input:  {_norm(m)}\n decoded: {_norm(decoded)}\n wire:\n{wire}"
        )
    # Sanity: the generator actually exercised the keyed path.
    assert keyed_seen > ITERATIONS // 4, f"keyed path under-exercised: {keyed_seen}/{ITERATIONS}"


def test_keyed_map_in_wrapper_and_nested_positions():
    """Route the keyed map through named-nested, single-key wrapper, expanded-item,
    and tabular-row-attachment positions."""
    r = random.Random(0x3C0DE)
    for i in range(ITERATIONS // 4):
        m = _gen_keyed_map(r)
        if m is None:
            continue
        pos = r.randint(0, 3)
        if pos == 0:
            payload = {"title": "prod", "servers": m}          # named-nested
        elif pos == 1:
            payload = {"wrap": m}                               # single-key wrapper
        elif pos == 2:
            payload = [{"id": 1, "data": m}, {"id": 2, "data": m}]  # tabular-row attachment
        else:
            payload = [m, {"z": 1}]                             # expanded array item
        wire = encode_generic(payload)
        decoded = decode_generic(wire)
        assert _deep_equal(_norm(payload), _norm(decoded)), (
            f"iter {i} pos {pos}: mismatch\n input: {_norm(payload)}\n decoded: {_norm(decoded)}\n wire:\n{wire}"
        )


def test_streaming_keyed_map_round_trip():
    """The streaming path (begin_keyed_map + write_row) has a fixed value schema:
    every member has every field present (null allowed, absent not expressible)."""
    r = random.Random(0x5417)
    for i in range(ITERATIONS):
        fields = _gen_value_fields(r, allow_gt=False)
        if not fields:
            continue
        key_label = "key"
        while key_label in fields:
            key_label = "_" + key_label
        n = 2 + r.randint(0, 6)
        keys = _gen_member_keys(r, n)
        if len(keys) < 2:
            continue
        expected = {}
        buf = io.StringIO()
        enc = GenericStreamEncoder(buf)
        enc.begin_keyed_map("m", key_label, fields)
        for k in keys:
            val_obj = {}
            row = [k]
            for f in fields:
                v = _gen_scalar(r)
                row.append(v)
                val_obj[f] = v
            enc.write_row(row)
            expected[k] = val_obj
        enc.end_array()
        enc.close()
        wire = buf.getvalue()
        want = {"m": expected}
        decoded = decode_generic(wire)
        assert _deep_equal(_norm(want), _norm(decoded)), (
            f"iter {i}: streaming mismatch\n want: {_norm(want)}\n got: {_norm(decoded)}\n wire:\n{wire}"
        )


def test_single_member_map_is_not_keyed():
    """SPEC 7.2a.1 clause 1: a single-member map is a section, not a keyed table."""
    r = random.Random(0xBEEF)
    for _ in range(2000):
        k = _gen_bare_key(r)
        inner = {f: _gen_scalar(r) for f in [_gen_bare_key(r), _gen_bare_key(r)]}
        m = {k: inner}
        wire = encode_generic(m)
        assert "[1:]" not in wire, f"single-member map should not be keyed:\n{wire}"
        decoded = decode_generic(wire)
        assert _deep_equal(_norm(m), _norm(decoded)), f"round-trip mismatch:\n{wire}"


def test_all_gt_value_fields_fall_back_to_sections():
    """SPEC 7.2a.1: a map whose value fields all contain '>' cannot be keyed
    (a '>' name is not a tabular column) and falls back to Section 7.2."""
    m = {"a": {"x>y": 1}, "b": {"x>y": 2}}
    wire = encode_generic(m)
    assert ":]" not in wire, f"all-'>' map must not be keyed:\n{wire}"
    assert _deep_equal(_norm(m), _norm(decode_generic(wire)))


def test_all_empty_value_objects_fall_back():
    """A map whose values are all empty objects has an empty field union and is
    not keyed (SPEC 7.2a.1)."""
    m = {"a": {}, "b": {}}
    wire = encode_generic(m)
    assert ":]" not in wire, f"all-empty-value map must not be keyed:\n{wire}"
    assert _deep_equal(_norm(m), _norm(decode_generic(wire)))
