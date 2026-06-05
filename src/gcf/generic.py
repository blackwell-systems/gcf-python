"""GCF generic encoder: serializes arbitrary Python values into GCF tabular format."""

from __future__ import annotations

from typing import Any


def encode_generic(data: Any) -> str:
    """Encode any Python value into GCF tabular format.

    Unlike encode() which handles the graph Payload type, encode_generic()
    works on arbitrary dicts, lists, and primitives using GCF's tabular
    encoding grammar.

    Args:
        data: Any Python value (dict, list, primitive, or None).

    Returns:
        GCF-formatted text string.
    """
    if data is None or not isinstance(data, (dict, list)):
        return str(data) if data is not None else "-"
    lines: list[str] = []
    _encode_value(data, lines, depth=0)
    return "\n".join(lines) + "\n" if lines else "\n"


def _encode_value(value: Any, lines: list[str], depth: int) -> None:
    """Dispatch encoding based on value type."""
    if isinstance(value, dict):
        _encode_dict(value, lines, depth)
    elif isinstance(value, list):
        _encode_array(value, "items", lines, depth)
    else:
        lines.append(_indent(depth) + _format_value(value))


def _encode_dict(d: dict, lines: list[str], depth: int, name: str | None = None) -> None:
    """Encode a dict into key=value pairs with section headers for nested values."""
    prefix = _indent(depth)
    if name is not None:
        lines.append(f"{prefix}## {name}")
    for key, value in d.items():
        if isinstance(value, list):
            _encode_array(value, key, lines, depth)
        elif isinstance(value, dict):
            _encode_dict(value, lines, depth + 1, name=key)
        else:
            lines.append(f"{prefix}{key}={_format_value(value)}")


def _encode_array(items: list, name: str, lines: list[str], depth: int) -> None:
    """Encode a list, using tabular format for uniform dict lists."""
    prefix = _indent(depth)

    if not items:
        lines.append(f"{prefix}## {name} [0]")
        return

    if _is_uniform_dict_list(items):
        _encode_tabular(items, name, lines, depth)
    else:
        lines.append(f"{prefix}## {name} [{len(items)}]")
        for i, item in enumerate(items):
            if isinstance(item, dict):
                lines.append(f"{prefix}@{i}")
                _encode_dict(item, lines, depth + 1)
            else:
                lines.append(f"{prefix}@{i} {_format_value(item)}")


def _encode_tabular(items: list[dict], name: str, lines: list[str], depth: int) -> None:
    """Encode a uniform list of dicts as a tabular section."""
    prefix = _indent(depth)

    # Collect all keys from the first item to determine field order.
    all_keys = list(items[0].keys())
    primitive_fields = [k for k in all_keys if not isinstance(items[0][k], (dict, list))]
    nested_fields = [k for k in all_keys if isinstance(items[0][k], (dict, list))]

    # Header with field names (primitive fields only in the column spec).
    header = f"{prefix}## {name} [{len(items)}]{{{','.join(primitive_fields)}}}"
    lines.append(header)

    for i, item in enumerate(items):
        row_values = [_format_value(item.get(f)) for f in primitive_fields]
        row_str = "|".join(row_values)

        if nested_fields:
            lines.append(f"{prefix}@{i} {row_str}")
            for nk in nested_fields:
                nv = item.get(nk)
                if isinstance(nv, list):
                    _encode_array(nv, nk, lines, depth + 1)
                elif isinstance(nv, dict):
                    _encode_dict(nv, lines, depth + 1, name=nk)
        else:
            lines.append(f"{prefix}{row_str}")


def _is_uniform_dict_list(items: list) -> bool:
    """Check whether a list contains uniform dicts (same keys across items).

    Samples up to the first 5 items. Considers the list uniform if key
    overlap is at least 70% between consecutive items and the first item.
    """
    if not items or not isinstance(items[0], dict):
        return False

    sample = items[:5]
    if not all(isinstance(item, dict) for item in sample):
        return False

    if not sample:
        return False

    reference_keys = set(sample[0].keys())
    if not reference_keys:
        return False

    for item in sample[1:]:
        item_keys = set(item.keys())
        union = reference_keys | item_keys
        intersection = reference_keys & item_keys
        if not union or len(intersection) / len(union) < 0.7:
            return False

    return True


def _format_value(value: Any) -> str:
    """Format a single value for GCF output.

    None becomes "-". Booleans are lowercased. Numbers are unquoted.
    Strings containing "|" or newlines are quoted. Everything else is direct.
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if "|" in s or "\n" in s or s == "":
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _indent(depth: int) -> str:
    """Return indentation string for the given depth (2 spaces per level)."""
    return "  " * depth
