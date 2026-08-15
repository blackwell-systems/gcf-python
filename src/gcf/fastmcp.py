"""Optional FastMCP middleware for opt-in GCF response encoding.

This is a small integration helper for `FastMCP <https://gofastmcp.com>`_ servers.
It requires the ``fastmcp`` extra; the core ``gcf`` package stays
zero-dependency::

    pip install "gcf-python[fastmcp]"

Register it once on a FastMCP server::

    from gcf.fastmcp import GcfResponseMiddleware

    mcp.add_middleware(GcfResponseMiddleware())

When ``RESPONSE_FORMAT=gcf`` is set in the environment, each tool result whose
model-facing content is a single JSON text block is re-encoded as a GCF generic
wire, so the response uses fewer tokens when it crosses the LLM boundary. It is:

- **Opt-in** — nothing changes unless ``RESPONSE_FORMAT=gcf`` is set (or
  ``enabled=True`` is passed).
- **Lossless and fail-safe** — on any encoding error the original result is
  returned, so a tool call is never dropped over formatting.
- **Non-destructive** — only a lone JSON text block is re-encoded; a result
  carrying an image or any second block is left untouched, and the tool's
  ``structuredContent`` (if any) is preserved so output-schema validation and
  non-model clients keep receiving JSON.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

try:
    from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
    from fastmcp.tools.tool import ToolResult
    from mcp.types import TextContent
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "gcf.fastmcp requires the optional 'fastmcp' dependency: "
        'pip install "gcf-python[fastmcp]"'
    ) from exc

from .decode_generic import decode_generic
from .generic import encode_generic

logger = logging.getLogger(__name__)

DEFAULT_ENV_VAR = "RESPONSE_FORMAT"


def gcf_response_enabled(env_var: str = DEFAULT_ENV_VAR) -> bool:
    """Return True when ``env_var`` is set to ``gcf`` in the environment."""
    return os.environ.get(env_var, "").strip().lower() == "gcf"


class GcfResponseMiddleware(Middleware):
    """FastMCP middleware that re-encodes JSON tool results as GCF, opt-in.

    Args:
        env_var: Environment variable that gates encoding. Defaults to
            ``RESPONSE_FORMAT``; encoding is on when its value is ``gcf``.
        enabled: Force encoding on or off, bypassing the environment gate.
            ``None`` (the default) reads the environment on each call.
    """

    def __init__(
        self,
        *,
        env_var: str = DEFAULT_ENV_VAR,
        enabled: Optional[bool] = None,
    ) -> None:
        self._env_var = env_var
        self._enabled = enabled

    def _is_enabled(self) -> bool:
        if self._enabled is not None:
            return self._enabled
        return gcf_response_enabled(self._env_var)

    async def on_call_tool(
        self,
        context: "MiddlewareContext",
        call_next: "CallNext",
    ) -> "ToolResult":
        result = await call_next(context)

        if not self._is_enabled():
            return result

        payload = _json_payload(result)
        if payload is None:
            return result

        try:
            wire = encode_generic(payload)
            # Verify the wire decodes back to the same value before shipping it, so a
            # result is never replaced with an unparseable or lossy encoding.
            if decode_generic(wire) != payload:
                return result
        except Exception as exc:  # noqa: BLE001 - liveness over correctness of format
            logger.debug("GCF encoding skipped: %s", exc)
            return result

        return ToolResult(
            content=[TextContent(type="text", text=wire)],
            structured_content=result.structured_content,
        )


def _json_payload(result: "ToolResult") -> Optional[Any]:
    """The JSON value to encode, or None if the result is not a single JSON body.

    Only a result whose content is exactly one text block is re-encoded, so an
    image or other block sent alongside it is never dropped. ``structuredContent``
    (the tool's typed value) is preferred as the payload; otherwise the lone text
    block is parsed as JSON.
    """
    content = result.content or []
    if len(content) != 1 or not isinstance(content[0], TextContent):
        return None

    if result.structured_content is not None:
        return result.structured_content

    try:
        return json.loads(content[0].text)
    except (json.JSONDecodeError, ValueError):
        return None
