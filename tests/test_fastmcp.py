"""Tests for the optional gcf.fastmcp integration middleware.

Skipped cleanly when the 'fastmcp' extra is not installed.
"""

import asyncio
import json
import random
from types import SimpleNamespace

import pytest

pytest.importorskip("fastmcp")

from fastmcp.tools.tool import ToolResult  # noqa: E402
from mcp.types import TextContent  # noqa: E402

from gcf import decode_generic  # noqa: E402
from gcf.fastmcp import GcfResponseMiddleware, gcf_response_enabled  # noqa: E402


def _run(middleware, result):
    async def call_next(_context):
        return result

    return asyncio.run(middleware.on_call_tool(SimpleNamespace(), call_next))


def _result(*content, structured_content=None):
    return ToolResult(content=list(content), structured_content=structured_content)


def _text(result):
    return result.content[0].text


def _docs(n):
    return [{"id": i, "name": f"n{i}", "role": "admin" if i % 2 else "user"} for i in range(n)]


def test_gcf_response_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("RESPONSE_FORMAT", raising=False)
    assert gcf_response_enabled() is False
    for value in ("gcf", "GCF", " gcf "):
        monkeypatch.setenv("RESPONSE_FORMAT", value)
        assert gcf_response_enabled() is True
    monkeypatch.setenv("RESPONSE_FORMAT", "json")
    assert gcf_response_enabled() is False


def test_encodes_structured_content_as_gcf():
    data = {"rows": _docs(20)}
    result = _result(TextContent(type="text", text=json.dumps(data)), structured_content=data)

    out = _run(GcfResponseMiddleware(enabled=True), result)

    assert _text(out).startswith("GCF profile=generic")
    assert decode_generic(_text(out)) == data  # lossless round-trip
    assert out.structured_content == data  # preserved for non-model clients


def test_encodes_json_text_when_no_structured_content():
    data = _docs(20)
    result = _result(TextContent(type="text", text=json.dumps(data)))

    out = _run(GcfResponseMiddleware(enabled=True), result)

    assert _text(out).startswith("GCF profile=generic")
    assert decode_generic(_text(out)) == data


def test_disabled_leaves_result_unchanged():
    text = json.dumps(_docs(20))
    result = _result(TextContent(type="text", text=text))

    out = _run(GcfResponseMiddleware(enabled=False), result)

    assert _text(out) == text


def test_env_gate(monkeypatch):
    text = json.dumps(_docs(20))
    monkeypatch.delenv("RESPONSE_FORMAT", raising=False)
    out = _run(GcfResponseMiddleware(), _result(TextContent(type="text", text=text)))
    assert _text(out) == text  # env not set -> unchanged

    monkeypatch.setenv("RESPONSE_FORMAT", "gcf")
    out = _run(GcfResponseMiddleware(), _result(TextContent(type="text", text=text)))
    assert _text(out).startswith("GCF profile=generic")


def test_non_json_text_unchanged():
    result = _result(TextContent(type="text", text="a plain non-JSON message"))
    out = _run(GcfResponseMiddleware(enabled=True), result)
    assert _text(out) == "a plain non-JSON message"


def test_multiple_content_blocks_unchanged():
    text = json.dumps(_docs(20))
    result = _result(
        TextContent(type="text", text=text),
        TextContent(type="text", text="second block"),
    )

    out = _run(GcfResponseMiddleware(enabled=True), result)

    assert len(out.content) == 2
    assert out.content[0].text == text  # not rewritten (would drop the second block)


def test_encode_error_falls_back_to_json():
    # 2**63 is outside GCF's canonical int64 domain, so encode_generic raises and
    # the middleware returns the original JSON result rather than dropping the call.
    data = {"seq": 2**63}
    text = json.dumps(data)
    result = _result(TextContent(type="text", text=text), structured_content=data)

    out = _run(GcfResponseMiddleware(enabled=True), result)

    assert _text(out) == text


def test_never_grow_keeps_json_when_gcf_larger():
    # A tiny single-field object: GCF's header overhead exceeds the JSON, so the
    # never-grow guard keeps the JSON rather than emit a larger wire.
    data = {"ok": True}
    text = json.dumps(data)
    result = _result(TextContent(type="text", text=text), structured_content=data)

    out = _run(GcfResponseMiddleware(enabled=True), result)

    assert _text(out) == text
    assert not _text(out).startswith("GCF ")


# --- fuzz: the safety invariant on arbitrary JSON ---

# Characters that stress GCF's delimiter/quoting rules and unicode handling.
_CHARS = "abc 0|,\"\\\n\t\r:{}[]<>é☕日本語—"


def _rand_str(rng, lo=0, hi=12):
    return "".join(rng.choice(_CHARS) for _ in range(rng.randint(lo, hi)))


def _rand_scalar(rng):
    kind = rng.randint(0, 5)
    if kind == 0:
        return rng.randint(-1_000_000, 1_000_000)
    if kind == 1:
        return rng.choice([True, False, None])
    if kind == 2:
        return round(rng.uniform(-1e6, 1e6), 4)
    if kind == 3:
        # occasionally an integer outside the int64 domain -> encode must decline safely
        return rng.choice([2**63, -(2**63) - 1, 10**25])
    return _rand_str(rng)


def _rand_json(rng, depth=0):
    if depth >= 4 or rng.random() < 0.35:
        return _rand_scalar(rng)
    kind = rng.randint(0, 2)
    if kind == 0:
        return [_rand_json(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    if kind == 1:
        return {_rand_str(rng, 1, 8): _rand_json(rng, depth + 1) for _ in range(rng.randint(0, 5))}
    # array of uniform records (GCF's favorable shape)
    keys = [_rand_str(rng, 1, 6) for _ in range(rng.randint(1, 5))]
    return [{k: _rand_json(rng, depth + 2) for k in keys} for _ in range(rng.randint(0, 8))]


def test_fuzz_middleware_never_grows_corrupts_or_crashes():
    rng = random.Random(20260815)
    middleware = GcfResponseMiddleware(enabled=True)

    for _ in range(5000):
        payload = _rand_json(rng)
        text = json.dumps(payload)
        structured = payload if isinstance(payload, dict) else None
        result = _result(TextContent(type="text", text=text), structured_content=structured)

        out = _run(middleware, result)

        # Always exactly one text block; never dropped or multiplied.
        assert len(out.content) == 1
        got = out.content[0].text

        if got == text:
            continue  # declined -> original JSON kept (always safe)

        # Otherwise it MUST be a GCF wire that is smaller than the JSON (never-grow)
        # and round-trips to the exact payload.
        assert got.startswith("GCF profile=generic")
        assert len(got) < len(text)
        assert decode_generic(got) == payload
