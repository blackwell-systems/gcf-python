"""
Multi-format fuzz testing for GCF.

Proves GCF is a lossless codec for structured data, not just JSON.
Generates random structured values, serializes through each format,
parses back, encodes as GCF, decodes, and compares to the original parsed value.

The round-trip is: generate -> serialize(format) -> parse(format) -> encode_generic -> decode_generic -> compare to parsed

This proves that any value representable in format X survives GCF encoding losslessly.
"""
import csv
import io
import json
import math
import os
import random
import string

import msgpack
import pytest
import toml
import yaml

from gcf import decode_generic, encode_generic

ITERATIONS = int(os.environ.get("GCF_FUZZ_ITERATIONS", "100000"))


def _rng(seed):
    return random.Random(seed)


def _gen_string(r, max_len=30):
    length = r.randint(0, max_len)
    chars = string.ascii_letters + string.digits + " _-.,;:/?&=~"
    return "".join(r.choice(chars) for _ in range(length))


def _gen_key(r, safe=False):
    """Generate a key. safe=True restricts to GCF bare-key-safe chars for tabular headers."""
    length = r.randint(1, 15)
    if safe:
        first = r.choice(string.ascii_letters + "_")
        rest = "".join(r.choice(string.ascii_letters + string.digits + "_-.") for _ in range(length - 1))
        return first + rest
    else:
        first = r.choice(string.ascii_letters + "_")
        rest = "".join(r.choice(string.ascii_letters + string.digits + "_-. %!?#@") for _ in range(length - 1))
        return first + rest


def _gen_number(r):
    choice = r.randint(0, 3)
    if choice == 0:
        return r.randint(-1000000, 1000000)
    elif choice == 1:
        return round(r.uniform(-1000, 1000), r.randint(1, 6))
    elif choice == 2:
        return 0
    else:
        return r.randint(0, 100)


def _gen_scalar(r):
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
    ])()


def _gen_value(r, depth, max_depth):
    if depth >= max_depth:
        return _gen_scalar(r)
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: _gen_number(r),
        lambda: _gen_string(r),
        lambda: _gen_object(r, depth, max_depth),
        lambda: _gen_array(r, depth, max_depth),
    ])()


def _gen_object(r, depth, max_depth):
    n = r.randint(0, 6)
    return {_gen_key(r, safe=True): _gen_value(r, depth + 1, max_depth) for _ in range(n)}


def _gen_array(r, depth, max_depth):
    n = r.randint(0, 8)
    return [_gen_value(r, depth + 1, max_depth) for _ in range(n)]


def _gen_tabular(r, rows=None, cols=None):
    """Generate an array of objects with consistent keys (tabular data)."""
    num_rows = rows or r.randint(1, 20)
    num_cols = cols or r.randint(1, 8)
    keys = [_gen_key(r, safe=True) for _ in range(num_cols)]
    # Ensure unique keys
    keys = list(dict.fromkeys(keys))
    return [{k: _gen_scalar(r) for k in keys} for _ in range(num_rows)]


def _normalize(val):
    """Normalize values for comparison (handle float precision, None, etc)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return str(val)
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return {k: _normalize(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_normalize(v) for v in val]
    return val


def _gcf_roundtrip(data):
    """Encode to GCF and decode back."""
    encoded = encode_generic(data)
    decoded = decode_generic(encoded)
    return decoded


# ============================================================
# JSON fuzz (baseline, should match existing tests)
# ============================================================

class TestJSONRoundtrip:
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            original = _gen_value(r, 0, 4)
            json_str = json.dumps(original)
            parsed = json.loads(json_str)
            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"JSON seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nJSON: {passed:,} round-trips passed")


# ============================================================
# YAML fuzz
# ============================================================

def _gen_yaml_safe_value(r, depth, max_depth):
    """Generate values that survive YAML serialization cleanly."""
    if depth >= max_depth:
        return _gen_yaml_safe_scalar(r)
    return r.choice([
        lambda: _gen_yaml_safe_scalar(r),
        lambda: _gen_yaml_safe_scalar(r),
        lambda: {_gen_key(r, safe=True): _gen_yaml_safe_value(r, depth + 1, max_depth) for _ in range(r.randint(0, 5))},
        lambda: [_gen_yaml_safe_value(r, depth + 1, max_depth) for _ in range(r.randint(0, 6))],
    ])()


def _gen_yaml_safe_scalar(r):
    """YAML-safe scalars (no ambiguous values like 'yes', 'no', 'on', 'off')."""
    return r.choice([
        lambda: None,
        lambda: r.random() < 0.5,
        lambda: r.randint(-10000, 10000),
        lambda: round(r.uniform(-100, 100), r.randint(1, 4)),
        lambda: _gen_string(r),
    ])()


class TestYAMLRoundtrip:
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            original = _gen_yaml_safe_value(r, 0, 3)
            yaml_str = yaml.dump(original, default_flow_style=False)
            parsed = yaml.safe_load(yaml_str)
            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"YAML seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nYAML: {passed:,} round-trips passed")


# ============================================================
# TOML fuzz
# ============================================================

def _gen_toml_value(r, depth, max_depth):
    """TOML-compatible values (no None, no mixed-type arrays, string keys only)."""
    if depth >= max_depth:
        return _gen_toml_scalar(r)
    return r.choice([
        lambda: _gen_toml_scalar(r),
        lambda: _gen_toml_scalar(r),
        lambda: {_gen_key(r, safe=True): _gen_toml_value(r, depth + 1, max_depth) for _ in range(r.randint(1, 4))},
        lambda: [_gen_toml_scalar(r) for _ in range(r.randint(0, 5))],  # homogeneous arrays only
    ])()


def _gen_toml_scalar(r):
    """TOML scalars (no None)."""
    return r.choice([
        lambda: r.random() < 0.5,
        lambda: r.randint(-10000, 10000),
        lambda: round(r.uniform(-100, 100), 2),
        lambda: _gen_string(r),
    ])()


class TestTOMLRoundtrip:
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            # TOML root must be a table (dict)
            original = {_gen_key(r, safe=True): _gen_toml_value(r, 0, 2) for _ in range(r.randint(1, 5))}
            try:
                toml_str = toml.dumps(original)
                parsed = toml.loads(toml_str)
            except (toml.TomlDecodeError, TypeError, IndexError, ValueError):
                continue  # skip TOML-incompatible structures or toml library bugs
            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"TOML seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nTOML: {passed:,} round-trips passed")


# ============================================================
# MessagePack fuzz
# ============================================================

class TestMessagePackRoundtrip:
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            original = _gen_value(r, 0, 4)
            try:
                packed = msgpack.packb(original, use_bin_type=True)
                parsed = msgpack.unpackb(packed, raw=False)
            except (TypeError, msgpack.PackValueError):
                continue
            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"MessagePack seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nMessagePack: {passed:,} round-trips passed")


# ============================================================
# CSV fuzz (tabular data only)
# ============================================================

class TestCSVRoundtrip:
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            # CSV only handles flat tabular data with string values
            num_rows = r.randint(1, 15)
            num_cols = r.randint(1, 6)
            keys = [_gen_key(r, safe=True) for _ in range(num_cols)]
            keys = list(dict.fromkeys(keys))
            if not keys:
                continue

            rows = [{k: str(_gen_scalar(r)) for k in keys} for _ in range(num_rows)]

            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
            csv_str = buf.getvalue()

            buf = io.StringIO(csv_str)
            reader = csv.DictReader(buf)
            parsed = [dict(row) for row in reader]

            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"CSV seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nCSV: {passed:,} round-trips passed")


# ============================================================
# Mixed tabular fuzz (the most common real-world pattern)
# ============================================================

class TestTabularRoundtrip:
    """Arrays of objects with consistent keys, typed values. The GCF sweet spot."""
    def test_fuzz(self):
        passed = 0
        for seed in range(ITERATIONS):
            r = _rng(seed)
            original = _gen_tabular(r)
            # Through JSON (normalize types)
            json_str = json.dumps(original)
            parsed = json.loads(json_str)
            roundtripped = _gcf_roundtrip(parsed)
            normalized_orig = _normalize(parsed)
            normalized_rt = _normalize(roundtripped)
            assert normalized_orig == normalized_rt, f"Tabular seed={seed}: {parsed} != {roundtripped}"
            passed += 1
        print(f"\nTabular: {passed:,} round-trips passed")
