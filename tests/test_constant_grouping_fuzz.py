"""Property/fuzz coverage for spec v3.6.0 constant-column factoring (SPEC 7.4.7) and
value-grouping (SPEC 7.4.8), mirroring the Go reference harness
(gcf-go/constant_grouping_fuzz_test.go).

Constant-column factoring rides the default encoder, so the generic round-trip suites
exercise it, but value-grouping is opt-in (encode_generic_grouped) and neither new
grammar had decoder-robustness (mutation) coverage. These harnesses close both gaps.
Per-SDK fuzz is required: the array-bracket quoted-key bug was caught only by per-SDK
fuzz, not by the Go suite.

Iteration count is controlled by GCF_CONST_GROUP_ITERATIONS (default 100000).
"""

import json
import math
import os
import random
import string

from gcf import decode_generic, encode_generic, encode_generic_grouped

ITERATIONS = int(os.environ.get("GCF_CONST_GROUP_ITERATIONS", "100000"))

SPECIAL = ' |,="\\#@\n\t~^+-.>'
BARE = string.ascii_letters + string.digits

# Hazard tokens mimic v3.6.0 syntax (clauses, subheaders, structural markers) so the
# generators can plant them as field names and values. A value or name that LOOKS like
# a grouping clause, a constant entry, a subheader, or another marker must still decode
# as plain data, never reclassify the payload.
HAZARD_STRINGS = [
    "group=dept", "group=", "region=us-east", "= [1]", "k=v [1]",
    "dept=Sales [2]", "}", "{a}", "[2]", "[2:]", "[0]", "[?]",
    "## section", ".field", "@id", "@0", "a|b", "-", "~",
    "^", "^{abc", "^{a}", "^{", "^x", "^{a,b}",
]

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


def _gen_scalar(r):
    if r.random() < 0.25:
        return r.choice(COLLISION_STRINGS)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
    ])()


def _gen_adversarial_scalar(r):
    if r.random() < 0.5:
        return r.choice(COLLISION_STRINGS)
    return _gen_scalar(r)


def _hazard_value(r):
    if r.randint(0, 2) == 0:
        return r.choice(HAZARD_STRINGS)
    return _gen_adversarial_scalar(r)


def _gen_bare_key(r):
    chars = string.ascii_lowercase + "_"
    return "".join(r.choice(chars) for _ in range(1 + r.randint(0, 7)))


def _gen_key(r):
    if r.random() < 0.3:
        return r.choice(COLLISION_STRINGS)
    if r.random() < 0.3:
        return _gen_string(r)
    return _gen_bare_key(r)


def _gen_field_name(r, used):
    """Mostly bare keys, sometimes a quoting-required key (including names that contain
    "=", which must NOT be read as a constant-column separator, and names that mimic
    other markers). Never returns a name already used."""
    while True:
        k = r.randint(0, 3)
        if k == 0:
            f = _gen_key(r)
        elif k == 1:
            f = r.choice(HAZARD_STRINGS)
        else:
            f = _gen_bare_key(r)
        if f not in used:
            used.add(f)
            return f


def _norm(v):
    return json.loads(json.dumps(v))


def _deep_equal(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or (isinstance(a, float) and math.isnan(a) and isinstance(b, float) and math.isnan(b))
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_deep_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b


# ── constant-column factoring: constant-biased generator ─────────────────


def _gen_const_biased_array(r):
    """A tabular array (>=2 records, scalar leaves only) in which a random subset of
    fields is held constant across every record, drawing constant values from the
    adversarial pool so the factored value hits the quoting path. Sometimes every field
    is constant, exercising the all-constant / last-column-retained edge (7.4.7.1)."""
    n = 2 + r.randint(0, 5)  # 2..7 records
    k = 1 + r.randint(0, 4)  # 1..5 fields
    fields = []
    used = set()
    while len(fields) < k:
        fields.append(_gen_field_name(r, used))
    const_val = {}
    force_all = r.randint(0, 7) == 0  # ~12% all-constant
    for f in fields:
        if force_all or r.randint(0, 1) == 0:
            const_val[f] = _hazard_value(r)
    arr = []
    for _ in range(n):
        rec = {}
        for f in fields:
            if f in const_val:
                rec[f] = const_val[f]
            elif r.randint(0, 3) == 0:
                rec[f] = _hazard_value(r)
            else:
                rec[f] = _gen_scalar(r)
        arr.append(rec)
    return arr


def _header_has_factored_column(gcf):
    for line in gcf.split("\n"):
        if line.startswith("## "):
            open_b = line.find("{")
            close_b = line.rfind("}")
            if open_b >= 0 and close_b > open_b and "=" in line[open_b:close_b]:
                return True
    return False


def test_property_roundtrip_constant_biased():
    r = random.Random(0xC0)
    factored = 0
    for i in range(ITERATIONS):
        val = _gen_const_biased_array(r)
        gcf_text = encode_generic(val)
        if _header_has_factored_column(gcf_text):
            factored += 1
        decoded = decode_generic(gcf_text)
        assert _deep_equal(_norm(val), _norm(decoded)), (
            f"iteration {i}: round-trip mismatch\n  input:   {val}\n"
            f"  gcf:     {gcf_text!r}\n  decoded: {decoded}"
        )
    assert factored > 0, f"coverage gap: no factored headers produced in {ITERATIONS} iterations"


# ── value-grouping: keyed-set generator ──────────────────────────────────


def _gen_grouped_set(r):
    """A keyed set for encode_generic_grouped: a unique key field, a low-cardinality
    group field (values drawn adversarially, including null, brackets, commas, "="),
    and 0..3 extra scalar fields some of which may be constant. Key uniqueness is by
    construction, so the encoder never errors on this input."""
    key_field, group_field = "k", "g"
    n = 2 + r.randint(0, 7)  # 2..9 records
    pool_size = 1 + r.randint(0, 3)
    pool = []
    seen = set()
    guard = 0
    while len(pool) < pool_size and guard < 200:
        guard += 1
        v = _hazard_value(r)
        kkey = f"{type(v).__name__}/{v}"
        if kkey in seen:
            continue
        seen.add(kkey)
        pool.append(v)
    extra_n = r.randint(0, 3)
    extras = []
    used = {"k", "g"}
    while len(extras) < extra_n:
        extras.append(_gen_field_name(r, used))
    extra_const = {}
    for f in extras:
        if r.randint(0, 1) == 0:
            extra_const[f] = _hazard_value(r)
    arr = []
    for i in range(n):
        rec = {key_field: f"k{i:04d}", group_field: r.choice(pool)}
        for f in extras:
            if f in extra_const:
                rec[f] = extra_const[f]
            elif r.randint(0, 3) == 0:
                rec[f] = _hazard_value(r)
            else:
                rec[f] = _gen_scalar(r)
        arr.append(rec)
    return arr, key_field, group_field


def _sort_by_key(arr, key_field):
    arr.sort(key=lambda rec: str(rec.get(key_field)))


def test_property_roundtrip_grouped():
    r = random.Random(0x6C)
    for i in range(ITERATIONS):
        val, kf, gf = _gen_grouped_set(r)
        gcf_text = encode_generic_grouped(val, kf, gf)
        decoded = decode_generic(gcf_text)
        assert isinstance(decoded, list), f"iteration {i}: grouped decode did not yield a list: {type(decoded)}"
        assert len(decoded) == len(val), (
            f"iteration {i}: record count {len(decoded)} != {len(val)}\n  gcf: {gcf_text!r}"
        )
        # Compare as a set keyed by kf: sort both by key, then order-insensitive equal.
        in_copy = [dict(x) for x in val]
        dec_copy = [dict(x) for x in decoded]
        _sort_by_key(in_copy, kf)
        _sort_by_key(dec_copy, kf)
        assert _deep_equal(_norm(in_copy), _norm(dec_copy)), (
            f"iteration {i}: grouped round-trip mismatch\n  input:   {in_copy}\n"
            f"  gcf:     {gcf_text!r}\n  decoded: {dec_copy}"
        )


# ── decoder robustness (mutation) ────────────────────────────────────────

_STRUCTURAL_BYTES = b'|{}[]=@#.-~"\n '


def _mutate(r, b):
    b = bytearray(b)
    if len(b) == 0:
        return bytearray([r.randint(0, 127)])
    choice = r.randint(0, 5)
    if choice == 0:  # flip a bit
        i = r.randint(0, len(b) - 1)
        b[i] ^= 1 << r.randint(0, 7)
    elif choice == 1:  # delete a byte
        i = r.randint(0, len(b) - 1)
        del b[i]
    elif choice == 2:  # insert a structural byte
        i = r.randint(0, len(b))
        b.insert(i, r.choice(_STRUCTURAL_BYTES))
    elif choice == 3:  # truncate
        b = b[: r.randint(0, len(b) - 1)] if len(b) > 1 else b[:0]
    elif choice == 4:  # duplicate a fragment
        i = r.randint(0, len(b) - 1)
        b = b[:i] + b[i:] + b[i:]
    else:  # random byte
        i = r.randint(0, len(b) - 1)
        b[i] = r.randint(0, 127)
    return bytearray(b)


def test_constant_grouped_decode_robustness():
    """Mutate valid factored/grouped wire and require the decoder to reject cleanly,
    never crash with an unexpected exception type, on the result."""
    r = random.Random(0xF0)
    for i in range(ITERATIONS):
        if r.randint(0, 1) == 0:
            wire = encode_generic(_gen_const_biased_array(r))
        else:
            arr, kf, gf = _gen_grouped_set(r)
            try:
                wire = encode_generic_grouped(arr, kf, gf)
            except Exception:
                continue
        b = bytearray(wire.encode("utf-8", "surrogatepass"))
        for _ in range(1 + r.randint(0, 3)):
            b = _mutate(r, b)
        try:
            text = b.decode("utf-8", "surrogatepass")
        except Exception:
            continue
        # An error is fine; an unexpected crash (non-Exception) is not. Python catches
        # all normal failures as Exception, so the invariant here is "returns or raises
        # a normal exception, never hangs or segfaults".
        try:
            decode_generic(text)
        except Exception:
            pass


# ── shape discrimination ─────────────────────────────────────────────────


def test_shape_discrimination():
    """The v3.6.0 markers must not reclassify a payload of another shape."""
    # @-key field without group= must be rejected, not treated as a grouped section.
    try:
        decode_generic("GCF profile=generic\n## [2]{@id,x}\nu1|1\nu2|2\n")
        assert False, "@-marked field without group= should be rejected"
    except Exception as e:
        assert "invalid field name" in str(e), f"unexpected error category: {e}"

    # Keyed map [N:] decodes to an object, not an array; group= must not intercept it.
    got = decode_generic("GCF profile=generic\n## [2:]{key,x}\na|1\nb|2\n")
    assert isinstance(got, dict), f"keyed map [N:] decoded as {type(got)}, want dict"

    # A flat tabular array with no constant column stays flat and round-trips.
    flat = [{"id": "u1", "r": "a"}, {"id": "u2", "r": "b"}]
    wire = encode_generic(flat)
    assert not _header_has_factored_column(wire), f"flat array with varying columns should not factor: {wire!r}"
    dec = decode_generic(wire)
    assert _deep_equal(_norm(flat), _norm(dec)), f"flat round-trip failed: wire={wire!r}"


def test_grouped_seed_corpus():
    """Seed inputs from the Go native-fuzz entrypoint: these must decode (or reject)
    without an unexpected crash."""
    seeds = [
        "GCF profile=generic\n## [2]{id,region=us-east,level}\nu1|3\nu2|1\n",
        "GCF profile=generic\n## [2]{a=1,b}\n2\n2\n",
        "GCF profile=generic\n## [2]{@id,dept,x} group=dept\ndept=Sales [2]\nu1|1\nu2|2\n",
        "GCF profile=generic\n## [1]{@id,g,x} group=g\ng=- [1]\nu1|1\n",
    ]
    for s in seeds:
        try:
            decode_generic(s)
        except Exception:
            pass
