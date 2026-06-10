"""GCF streaming encoder: zero-buffering encode to any writable."""

from __future__ import annotations

import threading
from typing import Any, Protocol

from .constants import KIND_ABBREV
from .types import Edge, Symbol


class StreamWriter(Protocol):
    """Any object with a write(s: str) method."""

    def write(self, s: str) -> Any: ...


class StreamEncoder:
    """Writes GCF output incrementally as symbols and edges arrive.

    Zero buffering: each symbol/edge is written immediately. A trailer summary
    is emitted on close() with the final counts.

    Example::

        enc = StreamEncoder(sys.stdout, "context_for_task", token_budget=5000)
        enc.write_symbol(sym1)  # emitted immediately
        enc.write_edge(edge1)   # emitted immediately
        enc.close()             # emits ##! summary trailer
    """

    def __init__(
        self,
        writer: StreamWriter,
        tool: str,
        *,
        token_budget: int = 0,
        tokens_used: int = 0,
        pack_root: str = "",
        session: bool = False,
    ) -> None:
        self._w = writer
        self._lock = threading.Lock()
        self._sym_index: dict[str, int] = {}
        self._next_id = 0
        self._current_group = ""
        self._group_counts: dict[str, int] = {}
        self._edge_count = 0
        self._edges_started = False

        # Emit header immediately.
        parts = [f"GCF profile=graph tool={tool}"]
        if token_budget:
            parts.append(f"budget={token_budget}")
        if tokens_used:
            parts.append(f"tokens={tokens_used}")
        if pack_root:
            parts.append(f"pack_root={pack_root}")
        if session:
            parts.append("session=true")
        self._w.write(" ".join(parts) + "\n")

    def write_symbol(self, s: Symbol) -> None:
        """Emit a symbol line immediately. Group headers auto-managed."""
        with self._lock:
            group_names = ["targets", "related", "extended"]
            if s.distance < len(group_names):
                group_name = group_names[s.distance]
            else:
                group_name = f"distance_{s.distance}"

            if group_name != self._current_group:
                self._w.write(f"## {group_name}\n")
                self._current_group = group_name

            idx = self._next_id
            self._sym_index[s.qualified_name] = idx
            self._next_id += 1

            kind = KIND_ABBREV.get(s.kind, s.kind)
            self._w.write(f"@{idx} {kind} {s.qualified_name} {s.score:.2f} {s.provenance}\n")

            self._group_counts[group_name] = self._group_counts.get(group_name, 0) + 1

    def write_edge(self, e: Edge) -> None:
        """Emit an edge line immediately. Edges section header auto-emitted on first edge."""
        with self._lock:
            src_idx = self._sym_index.get(e.source)
            tgt_idx = self._sym_index.get(e.target)
            if src_idx is None or tgt_idx is None:
                return

            if not self._edges_started:
                self._w.write("## edges [?]\n")
                self._edges_started = True

            line = f"@{tgt_idx}<@{src_idx} {e.edge_type}"
            if e.status and e.status != "unchanged":
                line += f" {e.status}"
            self._w.write(line + "\n")
            self._edge_count += 1

    def write_bare_ref(self, qname: str, distance: int) -> None:
        """Emit a bare reference for a previously-transmitted symbol (session mode)."""
        with self._lock:
            group_names = ["targets", "related", "extended"]
            if distance < len(group_names):
                group_name = group_names[distance]
            else:
                group_name = f"distance_{distance}"

            if group_name != self._current_group:
                self._w.write(f"## {group_name}\n")
                self._current_group = group_name

            idx = self._next_id
            self._sym_index[qname] = idx
            self._next_id += 1
            self._w.write(f"@{idx}  # previously transmitted\n")
            self._group_counts[group_name] = self._group_counts.get(group_name, 0) + 1

    def close(self) -> None:
        """Emit ##! summary trailer with final counts."""
        with self._lock:
            counts: list[str] = []
            group_order = ["targets", "related", "extended"]

            for g in group_order:
                c = self._group_counts.get(g, 0)
                if c > 0:
                    counts.append(str(c))
            for g, c in self._group_counts.items():
                if g not in group_order and c > 0:
                    counts.append(str(c))
            if self._edge_count > 0:
                counts.append(str(self._edge_count))

            self._w.write(
                f"##! summary symbols={self._next_id} edges={self._edge_count}"
                f" counts={','.join(counts)}\n"
            )

    @property
    def symbol_count(self) -> int:
        """Number of symbols written so far."""
        return self._next_id

    @property
    def edge_count(self) -> int:
        """Number of edges written so far."""
        return self._edge_count
