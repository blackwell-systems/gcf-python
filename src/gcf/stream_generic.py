"""GCF v2.0 generic streaming encoder: zero-buffering tabular encode to any writable."""

from __future__ import annotations

import threading

from .scalar import format_scalar, format_key
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
        self._err: Exception | None = None
        self._w.write("GCF profile=generic\n")

    def begin_array(self, name: str, fields: Sequence[str]) -> None:
        """Start a tabular array section with deferred count [?]."""
        with self._lock:
            if self._err is not None:
                return
            if self._current is not None:
                self._end_array_locked()
            # A streaming tabular row has only flat columns; a field name containing
            # ">" is a flattened path the stream cannot represent (SPEC 8.3, 7.4.6).
            # Record the error and surface it at close().
            for f in fields:
                if ">" in f:
                    self._err = ValueError(
                        f"streaming field name {f!r} contains '>' "
                        "(a flattened path is not representable in a streaming row)"
                    )
                    return
            self._w.write(f"## {format_key(name)} [?]{{{_format_field_decl(fields)}}}\n")
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
        """Emit the ##! summary trailer with final counts.

        Raises any error recorded during encoding (e.g. a field name containing
        ">", which is not representable in a flat streaming row per SPEC 8.3).
        """
        with self._lock:
            if self._err is not None:
                raise self._err
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


def _format_field_decl(fields: Sequence[str]) -> str:
    """Quote each field name per Section 2.4 (via format_key), matching the
    buffered tabular header. The streaming header previously joined field names
    raw, so a name containing a delimiter or quote produced an invalid or
    ambiguous field declaration (SPEC 8.3)."""
    return ",".join(format_key(f) for f in fields)


def _format_value(v: Any) -> str:
    return format_scalar(v, "|")
