"""GCF v2.0 generic streaming encoder: zero-buffering tabular encode to any writable."""

from __future__ import annotations

import threading

from .scalar import format_scalar
from typing import Any, Sequence


class GenericStreamEncoder:
    """Writes GCF tabular output incrementally as rows arrive.

    Zero buffering: each row is written immediately. A trailer summary is
    emitted on close() with the final counts.

    Example::

        enc = GenericStreamEncoder(sys.stdout)
        enc.begin_array("employees", ["id", "name", "department", "salary"])
        enc.write_row([1, "Alice", "Engineering", 95000])
        enc.write_row([2, "Bob", "Sales", 72000])
        enc.end_array()
        enc.close()
    """

    def __init__(self, writer: Any) -> None:
        self._w = writer
        self._lock = threading.Lock()
        self._sections: list[tuple[str, int]] = []
        self._current: dict[str, Any] | None = None

    def begin_array(self, name: str, fields: Sequence[str]) -> None:
        """Start a tabular array section with deferred count [?]."""
        with self._lock:
            if self._current is not None:
                self._end_array_locked()
            self._w.write(f"## {name} [?]{{{','.join(fields)}}}\n")
            self._current = {"name": name, "fields": list(fields), "count": 0}

    def write_row(self, values: Sequence[Any]) -> None:
        """Emit a single pipe-separated row immediately."""
        with self._lock:
            if self._current is None:
                return
            parts = [_format_value(v) for v in values]
            self._w.write("|".join(parts) + "\n")
            self._current["count"] += 1

    def end_array(self) -> None:
        """Close the current array section and record its count."""
        with self._lock:
            self._end_array_locked()

    def write_kv(self, key: str, value: Any) -> None:
        """Emit a key=value line immediately."""
        with self._lock:
            self._w.write(f"{key}={_format_value(value)}\n")

    def write_section(self, name: str) -> None:
        """Start a nested object section (## key)."""
        with self._lock:
            if self._current is not None:
                self._end_array_locked()
            self._w.write(f"## {name}\n")

    def write_inline_array(self, name: str, values: Sequence[Any]) -> None:
        """Emit a primitive array inline: name[N]: val1,val2,val3"""
        with self._lock:
            parts = [_format_value(v) for v in values]
            self._w.write(f"{name}[{len(values)}]: {','.join(parts)}\n")

    def close(self) -> None:
        """Emit the ##! summary trailer with final counts."""
        with self._lock:
            if self._current is not None:
                self._end_array_locked()
            if not self._sections:
                return
            counts = [str(count) for _, count in self._sections]
            self._w.write(f"##! summary counts={','.join(counts)}\n")

    def _end_array_locked(self) -> None:
        if self._current is None:
            return
        self._sections.append((self._current["name"], self._current["count"]))
        self._current = None


def _format_value(v: Any) -> str:
    return format_scalar(v, "|")
