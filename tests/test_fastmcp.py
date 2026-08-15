"""Tests for the optional gcf.fastmcp integration middleware.

Skipped cleanly when the 'fastmcp' extra is not installed.
"""

import asyncio
import json
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
