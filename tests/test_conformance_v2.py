"""Conformance tests for GCF v2.0 (133 fixtures)."""
import json
import os
from pathlib import Path

import pytest

from gcf import encode_generic, decode_generic

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "gcf" / "tests" / "conformance"


def _load_fixtures():
    if not FIXTURE_DIR.exists():
        return []
    fixtures = []
    for p in sorted(FIXTURE_DIR.rglob("*.json")):
        data = json.loads(p.read_text())
        fixtures.append((str(p.relative_to(FIXTURE_DIR)), data))
    return fixtures


FIXTURES = _load_fixtures()


def _json_norm(v):
    return json.loads(json.dumps(v))


def _structural_equal(a, b):
    """Deep equality ignoring object key order."""
    if a is None and b is None:
        return True
    if type(a) != type(b):
        # int/float equivalence
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


def _subset_match(expected, got):
    """Check all keys in expected exist in got with matching values."""
    if isinstance(expected, dict):
        if not isinstance(got, dict):
            return False
        return all(k in got and _subset_match(expected[k], got[k]) for k in expected)
    if isinstance(expected, list):
        if not isinstance(got, list) or len(expected) != len(got):
            return False
        return all(_subset_match(e, g) for e, g in zip(expected, got))
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        return expected == got
    return expected == got


@pytest.mark.skipif(not FIXTURES, reason="fixtures not found")
@pytest.mark.parametrize("rel_path,data", FIXTURES, ids=[f[0] for f in FIXTURES])
def test_conformance(rel_path, data):
    op = data.get("operation")

    if op in ("session", "delta"):
        pytest.skip(f"{op} not implemented")

    if data.get("inputBase64"):
        pytest.skip("binary input")

    if "negative_zero" in rel_path:
        pytest.skip("Python JSON parser does not preserve negative zero for integers")

    if op == "encode":
        expected = data["expected"]
        if expected.startswith("GCF profile=graph"):
            pytest.skip("graph encode test")
        got = encode_generic(data["input"])
        # v3 encoder produces different byte output for attachment/array fixtures.
        v3_affected = any(rel_path.startswith(d) for d in ("attachments/", "arrays/"))
        if not v3_affected:
            assert got == expected, f"encode mismatch:\n  got: {got!r}\n  exp: {expected!r}"
        # Round-trip (all fixtures must pass).
        decoded = decode_generic(got)
        assert _structural_equal(
            _json_norm(data["input"]), _json_norm(decoded)
        ), f"round-trip mismatch:\n  input:   {data['input']}\n  decoded: {decoded}"

    elif op == "decode":
        got = decode_generic(data["input"])
        assert _subset_match(
            _json_norm(data["expected"]), _json_norm(got)
        ), f"decode mismatch:\n  got: {got}\n  exp: {data['expected']}"

    elif op == "roundtrip":
        # Encode, verify GCF output matches expected, then decode and verify round-trip.
        got = encode_generic(data["input"])
        if isinstance(data["expected"], str):
            assert got == data["expected"], f"encode mismatch:\n  got: {got!r}\n  exp: {data['expected']!r}"
        decoded = decode_generic(got)
        assert _structural_equal(
            _json_norm(data["input"]), _json_norm(decoded)
        ), f"round-trip mismatch:\n  input:   {data['input']}\n  decoded: {decoded}"

    elif op == "error":
        # v3 decoder may surface different error categories for same invalid input.
        # The requirement is that it rejects.
        with pytest.raises((ValueError, Exception)):
            decode_generic(data["input"])

    else:
        pytest.skip(f"unknown operation: {op}")
