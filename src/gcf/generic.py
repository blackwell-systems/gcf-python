"""GCF generic generic encoder: serializes arbitrary Python values into GCF generic profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scalar import format_scalar, format_key


@dataclass
class GenericOptions:
    """Options for controlling generic encoding behavior."""
    no_flatten: bool = False
    """When True, disables promotion of fixed-shape nested objects to path
    columns (e.g. "customer>name"). Nested objects use attachment syntax
    instead. Set when targeting open-weight models that show lower
    comprehension on flattened encoding."""


def encode_generic(data: Any, opts: GenericOptions | None = None) -> str:
    if opts is None:
        opts = GenericOptions()
    out: list[str] = ["GCF profile=generic"]
    _encode_root_value(data, out, opts)
    return "\n".join(out) + "\n"


def _encode_root_value(v: Any, out: list[str], opts: GenericOptions) -> None:
    if v is None:
        out.append("=-")
    elif isinstance(v, dict):
        _encode_object(v, out, 0, opts)
    elif isinstance(v, list):
        _encode_root_array(v, out, opts)
    else:
        out.append(f"={format_scalar(v)}")


def _encode_object(d: dict, out: list[str], depth: int, opts: GenericOptions) -> None:
    prefix = _indent(depth)
    for key, value in d.items():
        fk = format_key(key)
        if isinstance(value, dict):
            out.append(f"{prefix}## {fk}")
            _encode_object(value, out, depth + 1, opts)
        elif isinstance(value, list):
            _encode_named_array(fk, value, out, depth, opts)
        else:
            out.append(f"{prefix}{fk}={format_scalar(value)}")


def _encode_root_array(arr: list, out: list[str], opts: GenericOptions) -> None:
    if not arr:
        out.append("## [0]")
        return
    if _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"## [{len(arr)}]: {vals}")
        return
    fields = _tabular_fields(arr)
    if fields is not None:
        _encode_tabular("## ", arr, fields, out, 0, opts)
        return
    _encode_expanded("## ", arr, out, 0, opts)


def _encode_named_array(name: str, arr: list, out: list[str], depth: int, opts: GenericOptions) -> None:
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
        _encode_tabular(f"{prefix}## {name} ", arr, fields, out, depth, opts)
        return
    _encode_expanded(f"{prefix}## {name} ", arr, out, depth, opts)


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


# ── Nested object flattening (v3.2) ──────────────────────────────────────


def _analyze_flattenable(
    arr: list[dict], field_name: str, parent_path: str
) -> list[dict] | None:
    """Analyze whether a field can be flattened. Returns list of leaf descriptors or None."""
    # Field names containing ">" cannot be flattened (would create ambiguous paths).
    if ">" in field_name:
        return None
    canonical_shape: dict[str, str] | None = None  # key -> "scalar" | "nested"

    for item in arr:
        if field_name not in item or item[field_name] is None:
            continue
        v = item[field_name]
        if not isinstance(v, dict):
            return None
        if isinstance(v, list):
            return None

        keys = list(v.keys())

        if canonical_shape is None:
            canonical_shape = {}
            for k in keys:
                if ">" in k:
                    return None
                val = v[k]
                if isinstance(val, list):
                    return None
                elif isinstance(val, dict):
                    canonical_shape[k] = "nested"
                else:
                    canonical_shape[k] = "scalar"
        else:
            if len(keys) != len(canonical_shape):
                return None
            for k in keys:
                if k not in canonical_shape:
                    return None
                val = v[k]
                expected = canonical_shape[k]
                if expected == "scalar":
                    if isinstance(val, (dict, list)):
                        return None
                elif expected == "nested":
                    if isinstance(val, list):
                        return None
                    if val is not None and not isinstance(val, dict):
                        return None

    if canonical_shape is None:
        return None

    current_path = f"{parent_path}>{field_name}" if parent_path else field_name
    parent_keys = parent_path.split(">") + [field_name] if parent_path else [field_name]

    leaves: list[dict] = []
    for k in canonical_shape:
        if canonical_shape[k] == "scalar":
            leaves.append({"path": f"{current_path}>{k}", "keys": parent_keys + [k]})
        else:
            sub_arr = []
            for item in arr:
                if field_name not in item or item[field_name] is None:
                    sub_arr.append({})
                else:
                    sub_arr.append(item[field_name])
            sub_leaves = _analyze_flattenable(sub_arr, k, current_path)
            if sub_leaves is None or len(sub_leaves) == 0:
                return None
            leaves.extend(sub_leaves)

    # Guard: reject if any row has non-null object with all-null leaves.
    if leaves:
        for item in arr:
            if field_name not in item or item[field_name] is None:
                continue
            all_null = all(
                _resolve_key_chain(item, leaf["keys"])[0] is None
                and _resolve_key_chain(item, leaf["keys"])[1]
                for leaf in leaves
            )
            if all_null:
                return None

    return leaves


def _resolve_key_chain(item: Any, keys: list[str]) -> tuple[Any, bool]:
    """Traverse an object by key chain. Returns (value, exists)."""
    if not keys or not isinstance(item, dict):
        return None, False
    if keys[0] not in item:
        return None, False
    current = item[keys[0]]
    if current is None:
        return None, True
    for k in keys[1:]:
        if not isinstance(current, dict) or k not in current:
            return None, False
        current = current[k]
    return current, True


def _encode_tabular(
    header_prefix: str, arr: list[dict], fields: list[str], out: list[str], depth: int, opts: GenericOptions
) -> None:
    prefix = _indent(depth)

    # Phase 0: Analyze fields for flattening.
    flatten_map: dict[str, list[dict]] = {}
    if not opts.no_flatten:
        for f in fields:
            leaves = _analyze_flattenable(arr, f, "")
            if leaves and len(leaves) > 0:
                flatten_map[f] = leaves

    # Fields whose names contain ">" must not appear as tabular columns
    # because the decoder would interpret them as flattened path columns.
    # Track them for per-row attachment emission (spec rule 7.4.6.1.4).
    gt_fields = {f for f in fields if f not in flatten_map and ">" in f}

    # Build expanded column list.
    columns: list[dict] = []
    for f in fields:
        if f in gt_fields:
            continue
        if f in flatten_map:
            for leaf in flatten_map[f]:
                columns.append({"header": format_key(leaf["path"]), "type": "flat", "field": f, "keys": leaf["keys"]})
        else:
            columns.append({"header": format_key(f), "type": "original", "field": f, "keys": []})

    # If all fields were excluded (all contain ">"), fall back to expanded.
    if not columns:
        _encode_expanded(header_prefix, arr, out, depth, opts)
        return

    # Pre-compute inline schemas and shared array schemas (skip flattened fields).
    inline_schemas: dict[str, list[str]] = {}
    shared_arr_schemas: dict[str, list[str]] = {}
    for f in fields:
        if f in flatten_map:
            continue
        ifs = _inline_schema_fields(arr, f)
        if ifs is not None:
            inline_schemas[f] = ifs
        sas = _shared_array_schema(arr, f)
        if sas is not None:
            shared_arr_schemas[f] = sas

    header_fields = ",".join(col["header"] for col in columns)
    out.append(f"{header_prefix}[{len(arr)}]{{{header_fields}}}")

    for i, item in enumerate(arr):
        cells: list[str] = []
        attachments: list[tuple[str, Any, bool, list[str] | None]] = []
        row_has_attachment = False

        for col in columns:
            if col["type"] == "flat":
                keys = col["keys"]
                if keys[0] not in item:
                    cells.append("~")
                else:
                    top_val = item[keys[0]]
                    if top_val is None:
                        cells.append("-")
                    else:
                        val, exists = _resolve_key_chain(item, keys)
                        if not exists:
                            cells.append("~")
                        elif val is None:
                            cells.append("-")
                        else:
                            cells.append(format_scalar(val, "|"))
                continue

            f = col["field"]
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

        # Emit fields with ">" in their names as per-row attachments.
        for f in fields:
            if f not in gt_fields:
                continue
            if f not in item:
                continue
            row_has_attachment = True
            attachments.append((f, item[f], False, None))

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
                    _encode_attachment_array_shared(prefix, fk, att_val, out, depth + 2, sas, opts)
                else:
                    _encode_attachment_array(prefix, fk, att_val, out, depth + 2, opts)
            elif isinstance(att_val, dict):
                out.append(f"{prefix}.{fk} {{}}")
                _encode_object(att_val, out, depth + 2, opts)
            else:
                # Scalar attachment (e.g. field names containing ">").
                if att_val is None:
                    out.append(f"{prefix}.{fk} =-")
                else:
                    out.append(f"{prefix}.{fk} ={format_scalar(att_val)}")


def _encode_attachment_array(
    att_prefix: str, fk: str, arr: list, out: list[str], depth: int, opts: GenericOptions | None = None
) -> None:
    if opts is None:
        opts = GenericOptions()
    if not arr:
        out.append(f"{att_prefix}.{fk} [0]")
    elif _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{att_prefix}.{fk} [{len(arr)}]: {vals}")
    else:
        fields = _tabular_fields(arr)
        if fields is not None:
            _encode_tabular(f"{att_prefix}.{fk} ", arr, fields, out, depth, opts)
        else:
            _encode_expanded(f"{att_prefix}.{fk} ", arr, out, depth, opts)


def _encode_attachment_array_shared(
    att_prefix: str, fk: str, arr: list, out: list[str], depth: int, shared_fields: list[str], opts: GenericOptions | None = None
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
        _encode_attachment_array(att_prefix, fk, arr, out, depth, opts)


def _encode_expanded(header_prefix: str, arr: list, out: list[str], depth: int, opts: GenericOptions | None = None) -> None:
    if opts is None:
        opts = GenericOptions()
    prefix = _indent(depth)
    out.append(f"{header_prefix}[{len(arr)}]")
    for i, item in enumerate(arr):
        if isinstance(item, dict):
            out.append(f"{prefix}@{i} {{}}")
            _encode_object(item, out, depth + 1, opts)
        elif isinstance(item, list):
            _encode_expanded_array_item(prefix, i, item, out, depth, opts)
        else:
            out.append(f"{prefix}@{i} ={format_scalar(item)}")


def _encode_expanded_array_item(
    prefix: str, idx: int, arr: list, out: list[str], depth: int, opts: GenericOptions | None = None
) -> None:
    if opts is None:
        opts = GenericOptions()
    if not arr:
        out.append(f"{prefix}@{idx} [0]")
    elif _all_primitives(arr):
        vals = ",".join(format_scalar(v, ",") for v in arr)
        out.append(f"{prefix}@{idx} [{len(arr)}]: {vals}")
    else:
        fields = _tabular_fields(arr)
        if fields is not None:
            _encode_tabular(f"{prefix}@{idx} ", arr, fields, out, depth + 1, opts)
        else:
            _encode_expanded(f"{prefix}@{idx} ", arr, out, depth + 1, opts)


def _all_primitives(arr: list) -> bool:
    return all(not isinstance(v, (dict, list)) for v in arr)


def _indent(depth: int) -> str:
    return "  " * depth
