"""Property-based round-trip tests for GCF v2.0."""
import json
import math
import os
import random
import string

import pytest

from gcf import encode_generic, decode_generic, GenericOptions

ITERATIONS = int(os.environ.get("GCF_ITERATIONS", "100000"))


def _rng(seed):
    return random.Random(seed)


def _gen_value(r, depth, max_depth):
    if depth >= max_depth:
        return _gen_scalar(r)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
        lambda: _gen_string(r),
        lambda: _gen_object(r, depth, max_depth),
        lambda: _gen_object(r, depth, max_depth),
        lambda: _gen_array(r, depth, max_depth),
        lambda: _gen_array(r, depth, max_depth),
        lambda: _gen_scalar(r),
    ])()


def _gen_scalar(r):
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
        lambda: _gen_string(r),
    ])()


def _gen_number(r):
    return r.choice([
        lambda: 0,
        lambda: r.randint(0, 999),
        lambda: -r.randint(0, 999),
        lambda: r.randint(0, 999999) + r.random(),
        lambda: -0.0,
        lambda: (r.randint(1, 999)) * 1e18,
        lambda: (r.randint(1, 999)) * 1e-10,
    ])()


SPECIAL = ' |,="\\#@\n\t~^+-.>'
BARE = string.ascii_letters + string.digits


def _gen_string(r):
    n = r.randint(0, 19)
    return "".join(
        r.choice(SPECIAL) if r.random() < 0.2 else r.choice(BARE) for _ in range(n)
    )


def _gen_bare_key(r):
    chars = string.ascii_lowercase + "_"
    return "".join(r.choice(chars) for _ in range(1 + r.randint(0, 7)))


def _gen_object(r, depth, max_depth):
    n = r.randint(0, 5)
    d = {}
    for _ in range(n):
        k = _gen_bare_key(r)
        if k not in d:
            d[k] = _gen_value(r, depth + 1, max_depth)
    return d


def _gen_array(r, depth, max_depth):
    n = r.randint(0, 5)
    kind = r.randint(0, 3)
    if kind == 0:
        return [_gen_scalar(r) for _ in range(n)]
    if kind == 1:
        fields = [_gen_bare_key(r) for _ in range(1 + r.randint(0, 3))]
        return [
            {f: _gen_scalar(r) for f in fields if r.random() > 0.2}
            for _ in range(n)
        ]
    if kind == 2:
        arr = []
        for _ in range(n):
            obj = {_gen_bare_key(r): _gen_scalar(r)}
            if r.random() < 0.3 and depth + 1 < max_depth:
                obj[_gen_bare_key(r)] = _gen_value(r, depth + 2, max_depth)
            arr.append(obj)
        return arr
    return [_gen_value(r, depth + 1, max_depth) for _ in range(n)]


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


def _gen_adversarial_scalar(r):
    if r.random() < 0.3:
        return r.choice(COLLISION_STRINGS)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
    ])()


def _gen_adversarial_value(r, depth, max_depth):
    if depth >= max_depth:
        return _gen_adversarial_scalar(r)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: r.choice(COLLISION_STRINGS) if r.random() < 0.3 else _gen_string(r),
        lambda: _gen_adversarial_object(r, depth, max_depth),
        lambda: _gen_adversarial_array(r, depth, max_depth),
        lambda: {} if r.random() < 0.5 else [],
        lambda: _gen_adversarial_scalar(r),
    ])()


def _gen_adversarial_object(r, depth, max_depth):
    n = r.randint(0, 4)
    d = {}
    for _ in range(n):
        k = r.choice(COLLISION_STRINGS) if r.random() < 0.25 else _gen_bare_key(r)
        if k not in d:
            d[k] = _gen_adversarial_value(r, depth + 1, max_depth)
    return d


def _gen_adversarial_array(r, depth, max_depth):
    n = r.randint(0, 4)
    kind = r.randint(0, 4)
    if kind == 0:
        return [_gen_adversarial_scalar(r) for _ in range(n)]
    if kind == 1:
        fields = [_gen_bare_key(r), _gen_bare_key(r), _gen_bare_key(r)]
        arr = []
        for _ in range(n):
            obj = {}
            for f in fields:
                c = r.randint(0, 3)
                if c == 0:
                    pass
                elif c == 1:
                    obj[f] = None
                else:
                    obj[f] = _gen_adversarial_scalar(r)
            arr.append(obj)
        return arr
    if kind == 2:
        arr = []
        for _ in range(n):
            obj = {_gen_bare_key(r): _gen_adversarial_scalar(r)}
            if r.random() < 0.5 and depth + 1 < max_depth:
                nested = {_gen_bare_key(r): _gen_adversarial_scalar(r)}
                obj[_gen_bare_key(r)] = nested
            if r.random() < 0.3:
                obj[_gen_bare_key(r)] = [_gen_adversarial_scalar(r)]
            arr.append(obj)
        return arr
    if kind == 3:
        return [[_gen_adversarial_scalar(r) for _ in range(r.randint(0, 2))] for _ in range(n)]
    return [_gen_adversarial_value(r, depth + 1, max_depth) for _ in range(n)]


def _json_norm(v):
    return json.loads(json.dumps(v))


def _structural_equal(a, b):
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return a == b
    if type(a) != type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, dict):
        if set(a.keys()) != set(b.keys()):
            return False
        return all(_structural_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        if len(a) != len(b):
            return False
        return all(_structural_equal(x, y) for x, y in zip(a, b))
    return a == b


def test_random_roundtrip():
    r = _rng(42)
    for i in range(ITERATIONS):
        val = _gen_value(r, 0, 4)
        for no_flatten in (False, True):
            gcf = encode_generic(val, GenericOptions(no_flatten=no_flatten))
            decoded = decode_generic(gcf)
            a = _json_norm(val)
            b = _json_norm(decoded)
            assert _structural_equal(a, b), (
                f"iteration {i} no_flatten={no_flatten}: round-trip mismatch\n"
                f"  input:   {json.dumps(val)}\n"
                f"  decoded: {json.dumps(decoded)}\n"
                f"  gcf:     {gcf!r}"
            )


def test_adversarial_roundtrip():
    r = _rng(99)
    for i in range(ITERATIONS):
        val = _gen_adversarial_value(r, 0, 3)
        for no_flatten in (False, True):
            gcf = encode_generic(val, GenericOptions(no_flatten=no_flatten))
            decoded = decode_generic(gcf)
            a = _json_norm(val)
            b = _json_norm(decoded)
            assert _structural_equal(a, b), (
                f"iteration {i} no_flatten={no_flatten}: round-trip mismatch\n"
                f"  input:   {json.dumps(val)}\n"
                f"  decoded: {json.dumps(decoded)}\n"
                f"  gcf:     {gcf!r}"
            )
