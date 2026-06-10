"""GCF v2.0 generic encoder: serializes arbitrary Python values into GCF generic profile."""

from __future__ import annotations

from typing import Any

from .scalar import format_scalar, format_key


def encode_generic(data: Any) -> str:
    out: list[str] = ["GCF profile=generic"]
    _encode_root_value(data, out)
    return "\n".join(out) + "\n"


def _encode_root_value(v: Any, out: list[str]) -> None:
    if v is None:
        out.append("=-")
    elif isinstance(v, dict):
        _encode_object(v, out, 0)
    elif isinstance(v, list):
        _encode_root_array(v, out)
    else:
        out.append(f"={format_scalar(v)}")


def _encode_object(d: dict, out: list[str], depth: int) -> None:
    prefix = _indent(depth)
    for key, value in d.items():
        fk = format_key(key)
        if isinstance(value, dict):
            out.append(f"{prefix}## {fk}")
            _encode_object(value, out, depth + 1)
        elif isinstance(value, list):
            _encode_named_array(fk, value, out, depth)
        else:
            out.append(f"{prefix}{fk}={format_scalar(value)}")


def _encode_root_array(arr: list, out: list[str]) -> None:
    if not arr:
        out.append("## [0]")
        return
    if _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"## [{len(arr)}]: {vals}")
        return
    fields = _tabular_fields(arr)
    if fields is not None:
        _encode_tabular("## ", arr, fields, out, 0)
        return
    _encode_expanded("## ", arr, out, 0)


def _encode_named_array(name: str, arr: list, out: list[str], depth: int) -> None:
    prefix = _indent(depth)
    if not arr:
        out.append(f"{prefix}## {name} [0]")
        return
    if _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{prefix}{name}[{len(arr)}]: {vals}")
        return
    fields = _tabular_fields(arr)
    if fields is not None:
        _encode_tabular(f"{prefix}## {name} ", arr, fields, out, depth)
        return
    _encode_expanded(f"{prefix}## {name} ", arr, out, depth)


def _tabular_fields(arr: list) -> list[str] | None:
    if not arr:
        return None
    field_order: list[str] = []
    seen: set[str] = set()
    for item in arr:
        if not isinstance(item, dict):
            return None
        for k in item:
            if k not in seen:
                field_order.append(k)
                seen.add(k)
    return field_order if field_order else None


def _encode_tabular(
    header_prefix: str, arr: list[dict], fields: list[str], out: list[str], depth: int
) -> None:
    prefix = _indent(depth)
    fmt_fields = ",".join(format_key(f) for f in fields)
    out.append(f"{header_prefix}[{len(arr)}]{{{fmt_fields}}}")

    for i, item in enumerate(arr):
        cells: list[str] = []
        attachments: list[tuple[str, Any]] = []
        row_has_attachment = False

        for f in fields:
            if f not in item:
                cells.append("~")
                continue
            v = item[f]
            if v is None:
                cells.append("-")
                continue
            if isinstance(v, (dict, list)):
                cells.append("^")
                attachments.append((f, v))
                row_has_attachment = True
            else:
                cells.append(format_scalar(v, "|"))

        row = "|".join(cells)
        if row_has_attachment:
            out.append(f"{prefix}@{i} {row}")
        else:
            out.append(f"{prefix}{row}")

        for att_name, att_val in attachments:
            att_prefix = prefix + "  "
            fk = format_key(att_name)
            if isinstance(att_val, dict):
                out.append(f"{att_prefix}.{fk} {{}}")
                _encode_object(att_val, out, depth + 2)
            elif isinstance(att_val, list):
                _encode_attachment_array(att_prefix, fk, att_val, out, depth + 2)


def _encode_attachment_array(
    att_prefix: str, fk: str, arr: list, out: list[str], depth: int
) -> None:
    if not arr:
        out.append(f"{att_prefix}.{fk} [0]")
    elif _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{att_prefix}.{fk} [{len(arr)}]: {vals}")
    else:
        fields = _tabular_fields(arr)
        if fields is not None:
            _encode_tabular(f"{att_prefix}.{fk} ", arr, fields, out, depth)
        else:
            _encode_expanded(f"{att_prefix}.{fk} ", arr, out, depth)


def _encode_expanded(header_prefix: str, arr: list, out: list[str], depth: int) -> None:
    prefix = _indent(depth)
    out.append(f"{header_prefix}[{len(arr)}]")
    for i, item in enumerate(arr):
        if isinstance(item, dict):
            out.append(f"{prefix}@{i} {{}}")
            _encode_object(item, out, depth + 1)
        elif isinstance(item, list):
            _encode_expanded_array_item(prefix, i, item, out, depth)
        else:
            out.append(f"{prefix}@{i} ={format_scalar(item)}")


def _encode_expanded_array_item(
    prefix: str, idx: int, arr: list, out: list[str], depth: int
) -> None:
    if not arr:
        out.append(f"{prefix}@{idx} [0]")
    elif _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{prefix}@{idx} [{len(arr)}]: {vals}")
    else:
        fields = _tabular_fields(arr)
        if fields is not None:
            _encode_tabular(f"{prefix}@{idx} ", arr, fields, out, depth + 1)
        else:
            _encode_expanded(f"{prefix}@{idx} ", arr, out, depth + 1)


def _all_primitives(arr: list) -> bool:
    return all(not isinstance(v, (dict, list)) for v in arr)


def _indent(depth: int) -> str:
    return "  " * depth
