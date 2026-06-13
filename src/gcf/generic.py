"""GCF generic generic encoder: serializes arbitrary Python values into GCF generic profile."""

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


def _inline_schema_fields(arr: list[dict], field_name: str) -> list[str] | None:
    """Check if field is eligible for inline schema: all rows same flat object, 3+ keys, first row has it."""
    if not arr or field_name not in arr[0]:
        return None
    first_val = arr[0][field_name]
    if not isinstance(first_val, dict):
        return None

    canonical_keys: list[str] | None = None
    for item in arr:
        if field_name not in item or item[field_name] is None:
            continue
        v = item[field_name]
        if not isinstance(v, dict):
            return None
        keys = list(v.keys())
        for val in v.values():
            if isinstance(val, (dict, list)):
                return None
        if canonical_keys is None:
            canonical_keys = keys
        else:
            if keys != canonical_keys:
                return None
    if canonical_keys is None or len(canonical_keys) < 3:
        return None
    return canonical_keys


def _shared_array_schema(arr: list[dict], field_name: str) -> list[str] | None:
    """Check if array attachment has same tabular schema across all rows. First row must have it. All values must be scalars."""
    if not arr or field_name not in arr[0]:
        return None
    first_val = arr[0][field_name]
    if not isinstance(first_val, list):
        return None

    canonical_fields: list[str] | None = None
    for item in arr:
        if field_name not in item or item[field_name] is None:
            continue
        v = item[field_name]
        if not isinstance(v, list):
            return None
        fields = _tabular_fields(v)
        if fields is None:
            return None
        # All values in array items must be scalars.
        for arr_item in v:
            if not isinstance(arr_item, dict):
                return None
            for val in arr_item.values():
                if isinstance(val, (dict, list)):
                    return None
        if canonical_fields is None:
            canonical_fields = fields
        else:
            if fields != canonical_fields:
                return None
    return canonical_fields


def _encode_tabular(
    header_prefix: str, arr: list[dict], fields: list[str], out: list[str], depth: int
) -> None:
    prefix = _indent(depth)

    # Pre-compute inline schemas and shared array schemas.
    inline_schemas: dict[str, list[str]] = {}
    shared_arr_schemas: dict[str, list[str]] = {}
    for f in fields:
        ifs = _inline_schema_fields(arr, f)
        if ifs is not None:
            inline_schemas[f] = ifs
        sas = _shared_array_schema(arr, f)
        if sas is not None:
            shared_arr_schemas[f] = sas

    fmt_fields = ",".join(format_key(f) for f in fields)
    out.append(f"{header_prefix}[{len(arr)}]{{{fmt_fields}}}")

    for i, item in enumerate(arr):
        cells: list[str] = []
        attachments: list[tuple[str, Any, bool, list[str] | None]] = []  # (name, value, inline, inline_fields)
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
                ifs = inline_schemas.get(f)
                if ifs and isinstance(v, dict):
                    if i == 0:
                        fmt_if = ",".join(format_key(k) for k in ifs)
                        cells.append(f"^{{{fmt_if}}}")
                    else:
                        cells.append("^")
                    attachments.append((f, v, True, ifs))
                else:
                    cells.append("^")
                    attachments.append((f, v, False, None))
                row_has_attachment = True
            else:
                cells.append(format_scalar(v, "|"))

        row = "|".join(cells)
        if row_has_attachment:
            out.append(f"{prefix}@{i} {row}")
        else:
            out.append(f"{prefix}{row}")

        for att_name, att_val, is_inline, inline_fields in attachments:
            fk = format_key(att_name)
            if is_inline and inline_fields:
                # Inline: single pipe-delimited row, no prefix, no indent.
                vals = "|".join(
                    "~" if k not in att_val else format_scalar(att_val[k], "|")
                    for k in inline_fields
                )
                out.append(f"{prefix}{vals}")
            elif isinstance(att_val, list):
                sas = shared_arr_schemas.get(att_name)
                if sas and i > 0:
                    _encode_attachment_array_shared(prefix, fk, att_val, out, depth + 2, sas)
                else:
                    _encode_attachment_array(prefix, fk, att_val, out, depth + 2)
            elif isinstance(att_val, dict):
                out.append(f"{prefix}.{fk} {{}}")
                _encode_object(att_val, out, depth + 2)


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


def _encode_attachment_array_shared(
    att_prefix: str, fk: str, arr: list, out: list[str], depth: int, shared_fields: list[str]
) -> None:
    if not arr:
        out.append(f"{att_prefix}.{fk} [0]")
        return
    if _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{att_prefix}.{fk} [{len(arr)}]: {vals}")
        return
    # Verify fields match shared schema.
    fields = _tabular_fields(arr)
    if fields is not None and fields == shared_fields:
        # Omit {fields}, use shared schema.
        prefix = _indent(depth)
        out.append(f"{att_prefix}.{fk} [{len(arr)}]")
        for item in arr:
            cells = []
            for f in shared_fields:
                if f not in item:
                    cells.append("~")
                elif item[f] is None:
                    cells.append("-")
                else:
                    cells.append(format_scalar(item[f], "|"))
            out.append(f"{prefix}{'|'.join(cells)}")
    else:
        # Fields don't match: fall back to full encoding.
        _encode_attachment_array(att_prefix, fk, arr, out, depth)


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
