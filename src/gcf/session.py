"""Session-based deduplication for GCF encoding."""

from __future__ import annotations

import threading

from .constants import KIND_ABBREV
from .encode import _group_by_distance
from .types import Payload, Symbol


class Session:
    """Tracks symbols transmitted to a client, enabling subsequent responses
    to reference them by ID without full retransmission.

    Thread-safe: multiple tool handlers may encode concurrently within a session.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._symbols: dict[str, int] = {}  # qualified_name -> global session ID
        self._next_id: int = 0

    def transmitted(self, qname: str) -> bool:
        """Return True if the symbol has been sent in a previous response."""
        with self._lock:
            return qname in self._symbols

    def get_id(self, qname: str) -> int:
        """Return the session-global ID for a previously transmitted symbol.

        Returns -1 if not found.
        """
        with self._lock:
            return self._symbols.get(qname, -1)

    def record(self, symbols: list[Symbol]) -> None:
        """Mark symbols as transmitted and assign session-global IDs.

        Call this after a successful encode to register newly-sent symbols.
        """
        with self._lock:
            for sym in symbols:
                if sym.qualified_name not in self._symbols:
                    self._symbols[sym.qualified_name] = self._next_id
                    self._next_id += 1

    def size(self) -> int:
        """Return the number of symbols tracked in this session."""
        with self._lock:
            return len(self._symbols)

    def reset(self) -> None:
        """Clear the session state."""
        with self._lock:
            self._symbols.clear()
            self._next_id = 0


def encode_with_session(p: Payload, sess: Session | None = None) -> str:
    """Encode a payload with session deduplication.

    Symbols that were already transmitted in prior responses are emitted as
    bare references (`@N  # previously transmitted`) instead of full declarations.
    After encoding, newly-sent symbols are recorded in the session.

    Args:
        p: The payload to encode.
        sess: Optional session tracker. If None, encodes without deduplication.

    Returns:
        GCF-formatted text string.
    """
    if sess is None:
        from .encode import encode
        return encode(p)

    parts: list[str] = []

    # Build local ID mapping for this response.
    local_index: dict[str, int] = {}
    for i, s in enumerate(p.symbols):
        local_index[s.qualified_name] = i

    # Count valid edges.
    valid_edges = sum(
        1 for e in p.edges
        if e.source in local_index and e.target in local_index
    )

    # Header with session=true marker.
    header = (
        f"GCF tool={p.tool} budget={p.token_budget} tokens={p.tokens_used} "
        f"symbols={len(p.symbols)} edges={valid_edges} session=true"
    )
    if p.pack_root:
        header += f" pack_root={p.pack_root}"
    parts.append(header)

    # Track which symbols are new (need full declaration).
    new_symbols: list[Symbol] = []

    # Group by distance.
    groups = _group_by_distance(p.symbols)
    group_names = ["targets", "related", "extended"]

    for g_distance, g_symbols in groups:
        if not g_symbols:
            continue
        if g_distance < len(group_names):
            name = group_names[g_distance]
        else:
            name = f"distance_{g_distance}"
        parts.append(f"## {name}")

        for s in g_symbols:
            idx = local_index[s.qualified_name]
            if sess.transmitted(s.qualified_name):
                # Bare reference: symbol was sent in a prior response.
                parts.append(f"@{idx}  # previously transmitted")
            else:
                # Full declaration.
                kind = KIND_ABBREV.get(s.kind, s.kind)
                parts.append(
                    f"@{idx} {kind} {s.qualified_name} {s.score:.2f} {s.provenance}"
                )
                new_symbols.append(s)

    # Edges section.
    if p.edges:
        parts.append(f"## edges [{valid_edges}]")
        for e in p.edges:
            src_idx = local_index.get(e.source)
            tgt_idx = local_index.get(e.target)
            if src_idx is None or tgt_idx is None:
                continue
            line = f"@{tgt_idx}<@{src_idx} {e.edge_type}"
            if e.status and e.status != "unchanged":
                line += f" {e.status}"
            parts.append(line)

    # Record all new symbols in the session.
    sess.record(new_symbols)

    return "\n".join(parts) + "\n"
