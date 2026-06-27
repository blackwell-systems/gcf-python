"""GCF delta encoding: only added/removed symbols for incremental delivery."""

from __future__ import annotations

from .constants import KIND_ABBREV
from .types import DeltaPayload


def encode_delta(d: DeltaPayload) -> str:
    """Encode a DeltaPayload into GCF delta format.

    Args:
        d: The delta payload to encode.

    Returns:
        GCF delta-formatted text string.
    """
    parts: list[str] = []

    # Header.
    savings = 0.0
    if d.full_tokens > 0:
        savings = 100.0 * (1.0 - d.delta_tokens / d.full_tokens)

    parts.append(
        f"GCF profile=graph tool={d.tool} delta=true base_root={d.base_root} "
        f"new_root={d.new_root} tokens={d.delta_tokens} savings={savings:.0f}%"
    )

    # Removed symbols: short references (consumer already has the full declaration).
    if d.removed:
        parts.append("## removed")
        for s in d.removed:
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"{kind} {s.qualified_name}")

    # Added symbols: full declarations (consumer doesn't have these).
    if d.added:
        parts.append("## added")
        for i, s in enumerate(d.added):
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"@{i} {kind} {s.qualified_name} {s.score:.2f} {s.provenance}")

    # Removed edges.
    if d.removed_edges:
        parts.append("## edges_removed")
        for e in d.removed_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    # Added edges.
    if d.added_edges:
        parts.append("## edges_added")
        for e in d.added_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    return "\n".join(parts) + "\n"


def encode_delta_with_session(
    d: DeltaPayload,
    sess: "Session | None" = None,
) -> str:
    """Encode a DeltaPayload with session dedup for added symbols.

    Stacks delta and session dedup: symbols that are "added" relative to the
    previous payload but were transmitted in an earlier call become bare
    references instead of full declarations. After encoding, new symbols
    are recorded in the session.

    Args:
        d: The delta payload to encode.
        sess: Optional session tracker. If None, falls back to encode_delta.

    Returns:
        GCF delta-formatted text string.
    """
    if sess is None:
        return encode_delta(d)

    from .session import Session

    parts: list[str] = []

    savings = 0.0
    if d.full_tokens > 0:
        savings = 100.0 * (1.0 - d.delta_tokens / d.full_tokens)

    parts.append(
        f"GCF profile=graph tool={d.tool} delta=true base_root={d.base_root} "
        f"new_root={d.new_root} tokens={d.delta_tokens} savings={savings:.0f}% session=true"
    )

    # Removed symbols.
    if d.removed:
        parts.append("## removed")
        for s in d.removed:
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"{kind} {s.qualified_name}")

    # Added symbols: session-aware. Previously transmitted become bare refs.
    new_symbols = []
    bare_refs = []
    for s in d.added:
        if sess.transmitted(s.qualified_name):
            bare_refs.append(s)
        else:
            new_symbols.append(s)

    if bare_refs:
        parts.append(f"## ref [{len(bare_refs)}]")
        for s in bare_refs:
            sid = sess.get_id(s.qualified_name)
            parts.append(f"@{sid}  # previously transmitted")

    if new_symbols:
        parts.append("## added")
        for i, s in enumerate(new_symbols):
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"@{i} {kind} {s.qualified_name} {s.score:.2f} {s.provenance}")

    # Removed edges.
    if d.removed_edges:
        parts.append("## edges_removed")
        for e in d.removed_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    # Added edges.
    if d.added_edges:
        parts.append("## edges_added")
        for e in d.added_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    # Record new symbols in session.
    sess.record(new_symbols)

    return "\n".join(parts) + "\n"
