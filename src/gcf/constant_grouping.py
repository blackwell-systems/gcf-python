"""GCF v3.6.0 tabular column optimizations for the generic profile: constant-column
factoring (SPEC 7.4.7) and value-grouping (SPEC 7.4.8).

Constant-column factoring is mandatory canonical and lives in the encoder
(_encode_tabular, generic.py); the decode side and the opt-in grouped encoder are
here. The wire output of encode_generic_grouped is byte-identical to the Go reference
EncodeGenericGrouped.
"""

from __future__ import annotations

from typing import Any

from .scalar import (
    MISSING,
    format_key,
    format_scalar,
    is_bare_key,
    needs_quote,
    parse_quoted_string,
    parse_scalar,
    quote_string,
    split_respecting_quotes,
)


class FieldEntry:
    """One parsed entry of a tabular field declaration. A plain field has only a
    name. A constant column (SPEC 7.4.7) carries an unparsed value token after an
    unquoted "=". A key column (SPEC 7.4.8.1, 10a.1) carries a leading "@"."""

    __slots__ = ("name", "is_key", "is_const", "const_tok")

    def __init__(self, name: str = "", is_key: bool = False, is_const: bool = False, const_tok: str = ""):
        self.name = name
        self.is_key = is_key
        self.is_const = is_const
        self.const_tok = const_tok


def _quoted_string_end(s: str) -> int:
    """Index just past the closing quote of a quoted string starting at s[0], or -1
    if unterminated."""
    escaped = False
    i = 1
    while i < len(s):
        if escaped:
            escaped = False
            i += 1
            continue
        if s[i] == "\\":
            escaped = True
            i += 1
            continue
        if s[i] == '"':
            return i + 1
        i += 1
    return -1


def _split_name_value(r: str) -> tuple[str, str | None]:
    """Parse a field entry's name and optional "=value" tail. The name is a Section
    2a key (bare or quoted); the "=" that introduces a constant value is the first
    unquoted "=" after the (possibly quoted) name. A None value means the entry is a
    plain field (no "=")."""
    if r == "":
        raise ValueError("malformed_header_field: empty field entry")
    if r[0] == '"':
        end = _quoted_string_end(r)
        if end < 0:
            raise ValueError("unterminated_quote: field name")
        nm = parse_quoted_string(r[:end])
        after = r[end:]
        if after == "":
            return nm, None
        if after[0] == "=":
            return nm, after[1:]
        raise ValueError("malformed_header_field: unexpected characters after quoted field name")
    idx = r.find("=")
    if idx >= 0:
        nm = r[:idx]
        if nm == "":
            raise ValueError("malformed_header_field: empty field name")
        if not is_bare_key(nm):
            raise ValueError(f"invalid field name: {nm}")
        return nm, r[idx + 1:]
    if not is_bare_key(r):
        raise ValueError(f"invalid field name: {r}")
    return r, None


def parse_field_entries(decl_str: str) -> list[FieldEntry]:
    """Parse a {...} field declaration supporting "@" key markers and "name=value"
    constant columns. Commas, and the "=" boundary, are parsed respecting quoted
    names and quoted values (SPEC 7.4.7.2, mirroring 2a.3)."""
    if len(decl_str) < 2 or decl_str[0] != "{" or decl_str[-1] != "}":
        raise ValueError(f"invalid field declaration: {decl_str}")
    inner = decl_str[1:-1]
    if inner == "":
        return []
    raw = split_respecting_quotes(inner, ",")
    entries: list[FieldEntry] = []
    for r in raw:
        r = r.strip()
        e = FieldEntry()
        if r.startswith("@"):
            e.is_key = True
            r = r[1:]
        nm, val = _split_name_value(r)
        e.name = nm
        if val is not None:
            e.is_const = True
            e.const_tok = val
        entries.append(e)
    seen: set[str] = set()
    for e in entries:
        if e.name in seen:
            raise ValueError(f"duplicate_field_name: {e.name}")
        seen.add(e.name)
    return entries


def parse_const_value(tok: str) -> Any:
    """Parse a constant-column value token into a scalar (SPEC 7.4.7.2). The absent
    marker and empty/attachment tokens are rejected."""
    if tok == "":
        raise ValueError("invalid_const_value: empty constant value (the empty string is always quoted)")
    if tok == "~":
        raise ValueError("invalid_const_value: absent marker ~ is not valid in a field declaration")
    # Reject only a complete attachment marker, mirroring the encoder's Section 2.4
    # quoting predicate (bare "^", or "^{...}" ending in "}"). A "^{"-prefixed token with
    # no closing "}" (e.g. "^{abc") is a literal string the encoder leaves bare, so the
    # decoder must accept it as a scalar.
    if tok == "^" or (len(tok) >= 3 and tok[0] == "^" and tok[1] == "{" and tok[-1] == "}"):
        raise ValueError("invalid_const_value: attachment marker is not a scalar")
    return parse_scalar(tok, tabular_context=False)


def format_const_value(v: Any) -> str:
    """Format a scalar as a constant-column header value (SPEC 7.4.7.2): the Section
    2.4 obligation plus quoting when the value contains "}" (the "," case is already
    covered by needs_quote). Null is "-"."""
    if v is None:
        return "-"
    if isinstance(v, str):
        if needs_quote(v) or "}" in v:
            return quote_string(v)
        return v
    return format_scalar(v)


def _path_top_level(name: str) -> tuple[str, bool]:
    """Top-level group key of a flattened path column (SPEC 7.4.6) and True when the
    name is a valid path (contains ">" with all segments non-empty), mirroring
    _parse_tabular_body's path-column detection."""
    if ">" not in name:
        return "", False
    parts = name.split(">")
    for p in parts:
        if p == "":
            return "", False
    return parts[0], True


def decode_constant_array(lines, header_line, depth, entries, count, parse_tabular_body):
    """Parse a tabular array whose field declaration contains one or more constant
    columns (SPEC 7.4.7). Parse the rows with the bare (per-record) fields only, then
    rebuild each record in declaration order, inserting each constant at its position.
    Returns (records, lines_consumed_including_header)."""
    bare_fields: list[str] = []
    const_vals: dict[str, Any] = {}
    for e in entries:
        if e.is_const:
            const_vals[e.name] = parse_const_value(e.const_tok)
            continue
        bare_fields.append(e.name)
    if not bare_fields:
        raise ValueError("no_bare_column: every field is constant; a row must carry at least one per-record column")
    rows, consumed = parse_tabular_body(lines, header_line + 1, depth, bare_fields, count)
    if count >= 0 and len(rows) != count:
        raise ValueError(f"count_mismatch: declared {count}, got {len(rows)}")

    # Plan the output-key order over all entries, mirroring _parse_tabular_body: a bare
    # path column (contains ">") collapses to its top-level key at the first occurrence,
    # a plain field keeps its name, and a constant contributes its name at its position.
    plan: list[tuple[str, bool]] = []  # (name, is_const)
    in_plan: set[str] = set()
    seen_group: set[str] = set()
    for e in entries:
        if e.is_const:
            plan.append((e.name, True))
            in_plan.add(e.name)
            continue
        top, ok = _path_top_level(e.name)
        if ok:
            if top not in seen_group:
                seen_group.add(top)
                plan.append((top, False))
                in_plan.add(top)
            continue
        plan.append((e.name, False))
        in_plan.add(e.name)

    out: list[Any] = []
    for r in rows:
        rm = r if isinstance(r, dict) else {}
        nm: dict[str, Any] = {}
        for name, is_const in plan:
            if is_const:
                nm[name] = const_vals[name]
                continue
            if name in rm:
                nm[name] = rm[name]
        # Append any keys the record carries that were not in the plan (flatten-fallback
        # attachments, Section 7.4.6.1.4), in the record's own order.
        for k, v in rm.items():
            if k not in in_plan:
                nm[k] = v
        out.append(nm)
    return out, consumed + 1


def _parse_header_key(s: str) -> str:
    """Parse a Section 2a key (bare or quoted) that occupies the whole of s."""
    if s == "":
        raise ValueError("empty key")
    if s[0] == '"':
        end = _quoted_string_end(s)
        if end != len(s):
            raise ValueError(f"malformed quoted key: {s}")
        return parse_quoted_string(s)
    if not is_bare_key(s):
        raise ValueError(f"invalid key: {s}")
    return s


def _index_unquoted_eq(s: str) -> int:
    """Index of the first "=" outside a quoted string, or -1."""
    in_quote = False
    escaped = False
    for i, c in enumerate(s):
        if escaped:
            escaped = False
            continue
        if c == "\\" and in_quote:
            escaped = True
            continue
        if c == '"':
            in_quote = not in_quote
            continue
        if c == "=" and not in_quote:
            return i
    return -1


def _parse_count_value(s: str) -> int:
    """Count grammar (Section 4): decimal with no leading zero (except "0")."""
    if s == "0":
        return 0
    if not s or s[0] == "0":
        raise ValueError(f"invalid_count: {s}")
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"invalid_count: {s}")
    if str(n) != s:
        raise ValueError(f"invalid_count: {s}")
    return n


def _parse_group_subheader(content: str) -> tuple[str, Any, int]:
    """Parse a line of the form `{col}={value} [{count}]` (SPEC 7.4.8.3). The value
    runs from the first unquoted "=" to the final " [" that begins the count. Returns
    (col, value, count)."""
    if not content.endswith("]"):
        raise ValueError("invalid_group_header: subheader missing count bracket")
    cnt_open = content.rfind(" [")
    if cnt_open < 0:
        raise ValueError("invalid_group_header: subheader missing count bracket")
    count_str = content[cnt_open + 2: len(content) - 1]
    try:
        n = _parse_count_value(count_str)
    except ValueError:
        raise ValueError(f"invalid_count: {count_str}")
    if n == 0:
        raise ValueError("invalid_count: a group names at least one record")
    col_eq_val = content[:cnt_open]
    eq = _index_unquoted_eq(col_eq_val)
    if eq < 0:
        raise ValueError("invalid_group_header: subheader missing '='")
    try:
        col_name = _parse_header_key(col_eq_val[:eq])
    except ValueError as err:
        raise ValueError(f"invalid_group_header: {err}")
    val_tok = col_eq_val[eq + 1:]
    v = parse_const_value(val_tok)
    return col_name, v, n


def decode_grouped_array(lines, header_line, depth, entries, group_clause, count):
    """Parse a value-grouped tabular array (SPEC 7.4.8). group_clause is the trimmed
    text after the field declaration's "}" (beginning with "group=").
    Returns (records, lines_consumed)."""
    if not group_clause.startswith("group="):
        raise ValueError("invalid_group_header: malformed group clause")
    try:
        group_col = _parse_header_key(group_clause[len("group="):].strip())
    except ValueError as err:
        raise ValueError(f"invalid_group_header: {err}")

    key_count = 0
    key_name = ""
    for e in entries:
        if e.is_key:
            key_count += 1
            key_name = e.name
    if key_count != 1:
        raise ValueError("invalid_group_header: a grouped section requires exactly one @ key column")

    # Validate the grouping column: present, not the key, not a constant column.
    group_entry: FieldEntry | None = None
    for e in entries:
        if e.name == group_col:
            group_entry = e
            break
    if group_entry is None:
        raise ValueError(f'invalid_group_header: group column "{group_col}" is not a declared field')
    if group_entry.is_key:
        raise ValueError(f'invalid_group_header: group column "{group_col}" is the key column')
    if group_entry.is_const:
        raise ValueError(f'invalid_group_header: group column "{group_col}" is a constant column')

    # Per-record (bare) fields are the non-constant fields other than the grouping
    # column; the key column is included.
    bare_fields: list[str] = []
    const_vals: dict[str, Any] = {}
    for e in entries:
        if e.is_const:
            const_vals[e.name] = parse_const_value(e.const_tok)
            continue
        if e.name == group_col:
            continue
        bare_fields.append(e.name)

    indent = "  " * depth
    records: list[Any] = []
    seen_groups: set[str] = set()
    seen_keys: set[str] = set()
    total = 0
    i = header_line + 1
    while i < len(lines):
        content = lines[i]
        if depth > 0:
            if not content.startswith(indent):
                break
            content = content[len(indent):]
        if content.startswith("## ") or content.startswith("##!"):
            break

        col, group_val, gcount = _parse_group_subheader(content)
        if col != group_col:
            raise ValueError(
                f'invalid_group_header: subheader column "{col}" does not match group column "{group_col}"'
            )
        gkey = format_scalar(group_val)
        if gkey in seen_groups:
            raise ValueError(f"duplicate_group: {gkey}")
        seen_groups.add(gkey)
        i += 1

        for _n in range(gcount):
            if i >= len(lines):
                raise ValueError(f'count_mismatch: group "{gkey}" declared {gcount} rows, found fewer')
            row_content = lines[i]
            if depth > 0:
                if not row_content.startswith(indent):
                    raise ValueError(f'count_mismatch: group "{gkey}" declared {gcount} rows, found fewer')
                row_content = row_content[len(indent):]
            if row_content.startswith("## ") or row_content.startswith("##!"):
                raise ValueError(f'count_mismatch: group "{gkey}" declared {gcount} rows, found fewer')
            cells = split_respecting_quotes(row_content, "|")
            if len(cells) != len(bare_fields):
                raise ValueError(f"row_width_mismatch: expected {len(bare_fields)} fields, got {len(cells)}")
            bare_vals: dict[str, Any] = {}
            for j, f in enumerate(bare_fields):
                cell = cells[j]
                # Only a complete attachment marker (bare "^" or "^{...}" ending in "}")
                # is forbidden; a "^{"-prefixed cell without a closing "}" is a literal
                # row scalar, not an attachment.
                if cell == "^" or (len(cell) >= 3 and cell[0] == "^" and cell[1] == "{" and cell[-1] == "}"):
                    raise ValueError("invalid_group_header: grouped records must not carry attachments")
                pv = parse_scalar(cell, tabular_context=True)
                if pv is MISSING:
                    continue
                bare_vals[f] = pv
            nm: dict[str, Any] = {}
            for e in entries:
                if e.name == group_col:
                    nm[e.name] = group_val
                elif e.is_const:
                    nm[e.name] = const_vals[e.name]
                else:
                    if e.name in bare_vals:
                        nm[e.name] = bare_vals[e.name]
            if key_name not in nm:
                raise ValueError(f'invalid_group_header: record missing key column "{key_name}"')
            ks = format_scalar(nm[key_name])
            if ks in seen_keys:
                raise ValueError(f"duplicate_key: {ks}")
            seen_keys.add(ks)
            records.append(nm)
            i += 1
        total += gcount

    if count >= 0 and total != count:
        raise ValueError(f"count_mismatch: declared {count}, got {total}")
    return records, i - header_line


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


def encode_generic_grouped(data: Any, key_field: str, group_field: str) -> str:
    """Encode an array of uniform records as a value-grouped keyed set (SPEC 7.4.8):
    opt-in, never the canonical default. key_field is the unique identity column
    (emitted @-marked); group_field is the low-cardinality column the records are
    clustered by. Other constant columns are factored (SPEC 7.4.7). It raises when the
    array is not a keyed set the grammar can represent: a missing key/group field, a
    non-unique key, key == group, or any record needing an attachment (nested value),
    which grouped rows do not carry in this version.

    The wire output is byte-identical to the Go reference EncodeGenericGrouped."""
    if not isinstance(data, list):
        raise ValueError("value-grouping requires a JSON array")
    arr = data
    if len(arr) == 0:
        raise ValueError("value-grouping requires a non-empty array")
    if key_field == group_field:
        raise ValueError("value-grouping: key field and group field must differ")
    for item in arr:
        if not isinstance(item, dict):
            raise ValueError("value-grouping requires an array of objects")
    fields = _tabular_fields(arr)
    if fields is None:
        raise ValueError("value-grouping requires an array of objects with fields")
    if key_field not in fields:
        raise ValueError(f'value-grouping: key field "{key_field}" not present in the records')
    if group_field not in fields:
        raise ValueError(f'value-grouping: group field "{group_field}" not present in the records')

    key_seen: set[str] = set()
    for item in arr:
        for f in fields:
            if f not in item:
                continue
            val = item[f]
            if isinstance(val, (dict, list)):
                raise ValueError(f'value-grouping does not support nested values in this version: field "{f}"')
        if key_field not in item or item[key_field] is None:
            raise ValueError(f'value-grouping: key field "{key_field}" missing in a record')
        ks = format_scalar(item[key_field])
        if ks in key_seen:
            raise ValueError(f'value-grouping: key field "{key_field}" is not unique ({ks})')
        key_seen.add(ks)

    # Constant columns (excluding key and group), factored per SPEC 7.4.7.
    const_val: dict[str, str] = {}
    if len(arr) >= 2:
        for f in fields:
            if f == key_field or f == group_field:
                continue
            first = ""
            first_set = False
            isc = True
            for item in arr:
                if f not in item:
                    isc = False
                    break
                cv = format_const_value(item[f])
                if not first_set:
                    first = cv
                    first_set = True
                elif cv != first:
                    isc = False
                    break
            if isc:
                const_val[f] = first

    header_fields: list[str] = []
    for f in fields:
        if f == key_field:
            header_fields.append("@" + format_key(f))
        elif f == group_field:
            header_fields.append(format_key(f))
        else:
            if f in const_val:
                header_fields.append(format_key(f) + "=" + const_val[f])
            else:
                header_fields.append(format_key(f))

    bare_fields: list[str] = []
    for f in fields:
        if f == group_field:
            continue
        if f in const_val:
            continue
        bare_fields.append(f)

    group_order: list[str] = []
    group_members: dict[str, list[Any]] = {}
    group_val_raw: dict[str, Any] = {}
    for item in arr:
        gv = item.get(group_field)
        gk = format_scalar(gv)
        if gk not in group_members:
            group_order.append(gk)
            group_members[gk] = []
            group_val_raw[gk] = gv
        group_members[gk].append(item)

    out: list[str] = ["GCF profile=generic"]
    out.append(f"## [{len(arr)}]{{{','.join(header_fields)}}} group={format_key(group_field)}")
    for gk in group_order:
        members = group_members[gk]
        gv_str = format_scalar(group_val_raw[gk])
        out.append(f"{format_key(group_field)}={gv_str} [{len(members)}]")
        for item in members:
            cells: list[str] = []
            for f in bare_fields:
                if f not in item:
                    cells.append("~")
                elif item[f] is None:
                    cells.append("-")
                else:
                    cells.append(format_scalar(item[f], "|"))
            out.append("|".join(cells))
    return "\n".join(out) + "\n"
