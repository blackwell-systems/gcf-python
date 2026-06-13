"""GCF generic generic decoder: parses GCF generic or graph profile text back to Python objects."""

from __future__ import annotations

from typing import Any

from .decode import decode
from .scalar import (
    parse_scalar, parse_quoted_string, split_respecting_quotes, split_field_decl,
    is_bare_key, MISSING, ATTACHMENT,
)


def decode_generic(input_text: str) -> Any:
    input_text = input_text.rstrip("\n\r")
    if not input_text:
        raise ValueError("missing_header: empty input")

    lines = input_text.split("\n")
    header = lines[0].rstrip("\r")
    if not header.startswith("GCF "):
        raise ValueError("missing_header: first line does not begin with GCF")

    profile = _parse_header_profile(header)

    if profile == "graph":
        p = decode(input_text)
        return {
            "tool": p.tool,
            "tokenBudget": p.token_budget,
            "tokensUsed": p.tokens_used,
            "packRoot": p.pack_root or "",
            "symbols": [
                {
                    "qualifiedName": s.qualified_name,
                    "kind": s.kind,
                    "score": s.score,
                    "provenance": s.provenance,
                    "distance": s.distance,
                }
                for s in p.symbols
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "edgeType": e.edge_type,
                    "status": e.status or "",
                }
                for e in p.edges
            ],
        }

    if profile != "generic":
        raise ValueError(f"unknown_profile: {profile}")

    content_lines: list[str] = []
    summary_line = ""
    deferred_count = 0
    for line in lines[1:]:
        line = line.rstrip("\r")
        if line == "":
            continue
        for j, c in enumerate(line):
            if c == "\t":
                raise ValueError("tab_indentation: tabs in leading whitespace")
            if c != " ":
                break
        trimmed = line.lstrip()
        if trimmed.startswith("# "):
            continue
        if trimmed.startswith("##! "):
            summary_line = trimmed
            continue
        if trimmed.startswith("## ") and "[?]" in trimmed:
            deferred_count += 1
        content_lines.append(line)

    if summary_line and deferred_count > 0:
        _validate_summary_counts(summary_line, deferred_count, content_lines)

    if not content_lines:
        return {}

    first = content_lines[0].lstrip()

    if first.startswith("="):
        if len(content_lines) > 1:
            raise ValueError("trailing_characters: extra lines after root scalar")
        return parse_scalar(first[1:])

    if first.startswith("## ["):
        arr, _ = _parse_array_from_header(content_lines, 0, 0, first[3:])
        return arr

    result: dict[str, Any] = {}
    _parse_object_body(content_lines, 0, 0, result)
    return result


def _parse_header_profile(header: str) -> str:
    parts = header.split()
    if len(parts) < 2:
        raise ValueError("missing_profile")
    seen: set[str] = set()
    profile = ""
    for p in parts[1:]:
        eq = p.find("=")
        if eq < 0:
            raise ValueError(f"malformed_header_field: {p}")
        key = p[:eq]
        if key in seen:
            raise ValueError(f"duplicate_header_field: {key}")
        seen.add(key)
        if key == "profile":
            profile = p[eq + 1:]
    if not profile:
        raise ValueError("missing_profile")
    return profile


def _parse_object_body(
    lines: list[str], start: int, depth: int, out: dict[str, Any]
) -> int:
    ind = "  " * depth
    i = start
    while i < len(lines):
        line = lines[i]
        if depth > 0 and not line.startswith(ind):
            break
        content = line[len(ind):] if depth > 0 else line
        if content and content[0] == " ":
            raise ValueError("invalid_indent: indentation increases by more than one level")

        if content.startswith("## "):
            hdr = content[3:]
            bi = hdr.find(" [")
            if bi >= 0:
                name = _parse_key_from_header(hdr[:bi])
                _check_dup(out, name)
                arr, consumed = _parse_array_from_header(lines, i, depth, hdr[bi:])
                out[name] = arr
                i += consumed
                continue
            name = _parse_key_from_header(hdr)
            _check_dup(out, name)
            i += 1
            nested: dict[str, Any] = {}
            consumed = _parse_object_body(lines, i, depth + 1, nested)
            out[name] = nested
            i += consumed
            continue

        if not content.startswith("@") and not content.startswith("##"):
            bracket_idx = content.find("[")
            if bracket_idx > 0:
                rest = content[bracket_idx:]
                close_idx = rest.find("]")
                if close_idx >= 0:
                    after = rest[close_idx + 1:]
                    if after.startswith(": ") or after == ":":
                        name = _parse_key_from_header(content[:bracket_idx])
                        _check_dup(out, name)
                        arr, _ = _parse_array_from_header(lines, i, depth, rest)
                        out[name] = arr
                        i += 1
                        continue

        eq_idx = _find_kv_split(content)
        if eq_idx > 0:
            name = _parse_key_from_header(content[:eq_idx])
            _check_dup(out, name)
            out[name] = parse_scalar(content[eq_idx + 1:])
            i += 1
            continue

        i += 1
    return i - start


def _find_kv_split(s: str) -> int:
    if not s:
        return -1
    if s[0] == '"':
        i = 1
        while i < len(s):
            if s[i] == "\\":
                i += 2
                continue
            if s[i] == '"':
                return i + 1 if i + 1 < len(s) and s[i + 1] == "=" else -1
            i += 1
        return -1
    return s.find("=")


def _parse_key_from_header(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"':
        return parse_quoted_string(s)
    return s


def _check_dup(d: dict, key: str) -> None:
    if key in d:
        raise ValueError(f"duplicate_key: {key}")


def _parse_array_from_header(
    lines: list[str], header_line: int, depth: int, bracket_part: str
) -> tuple[Any, int]:
    bp = bracket_part.lstrip()
    if not bp.startswith("["):
        raise ValueError("invalid_count")
    close = bp.find("]")
    if close < 0:
        raise ValueError("invalid_count")
    count_str = bp[1:close]
    after = bp[close + 1:]
    count = -1
    if count_str != "?":
        count = _parse_count(count_str)

    if count == 0 and not after.startswith("{") and not after.startswith(":"):
        return [], 1

    if after.startswith(": ") or after == ":":
        vals_str = after[2:] if after.startswith(": ") else ""
        if not vals_str:
            if count >= 0 and count != 0:
                raise ValueError(f"count_mismatch: declared {count}, got 0")
            return [], 1
        vals = split_respecting_quotes(vals_str, ",")
        if count >= 0 and len(vals) != count:
            raise ValueError(f"count_mismatch: declared {count}, got {len(vals)}")
        return [parse_scalar(v.strip()) for v in vals], 1

    if after.startswith("{"):
        brace_end = _find_closing_brace(after)
        if brace_end < 0:
            raise ValueError("invalid field declaration")
        fields = split_field_decl(after[:brace_end + 1])
        rows, consumed = _parse_tabular_body(lines, header_line + 1, depth, fields, count)
        if count >= 0 and len(rows) != count:
            raise ValueError(f"count_mismatch: declared {count}, got {len(rows)}")
        return rows, consumed + 1

    items, consumed = _parse_expanded_body(lines, header_line + 1, depth)
    if count >= 0 and len(items) != count:
        raise ValueError(f"count_mismatch: declared {count}, got {len(items)}")
    return items, consumed + 1


def _find_closing_brace(s: str) -> int:
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
        if c == "}" and not in_quote:
            return i
    return -1


def _parse_attachment_name(rest: str) -> tuple[str, str]:
    if rest and rest[0] == '"':
        j = 1
        while j < len(rest):
            if rest[j] == "\\":
                j += 2
                continue
            if rest[j] == '"':
                name = parse_quoted_string(rest[:j + 1])
                return name, rest[j + 1:]
            j += 1
        return "", rest
    sp = rest.find(" ")
    if sp >= 0:
        return rest[:sp], rest[sp:]
    return rest, ""


def _parse_attachment(
    lines: list[str], line_idx: int, rest: str, depth: int, shared_schemas: dict[str, list[str]]
) -> tuple[str, Any, int, list[str] | None]:
    """Returns (name, value, consumed, parsed_fields)."""
    name, after_name = _parse_attachment_name(rest)
    if not name and not rest.startswith('""'):
        raise ValueError(f"invalid attachment: {rest}")
    after_name = after_name.lstrip()

    if after_name.startswith("{}"):
        nested: dict[str, Any] = {}
        consumed = _parse_object_body(lines, line_idx + 1, depth, nested)
        return name, nested, consumed + 1, None

    if after_name.startswith("["):
        cb = after_name.find("]")
        if cb < 0:
            raise ValueError("invalid_count: missing ]")
        after_close = after_name[cb + 1:]

        # [N]{fields}: has its own schema.
        if after_close.startswith("{"):
            end_brace = _find_closing_brace(after_close)
            parsed_fields: list[str] | None = None
            if end_brace >= 0:
                try:
                    parsed_fields = split_field_decl(after_close[:end_brace + 1])
                except Exception:
                    pass
            arr, consumed = _parse_array_from_header(lines, line_idx, depth, after_name)
            return name, arr, consumed, parsed_fields

        # [N]: inline primitive array: don't use shared schema.
        if after_close.startswith(": ") or after_close == ":":
            arr, consumed = _parse_array_from_header(lines, line_idx, depth, after_name)
            return name, arr, consumed, None

        # [N] without {fields}: check for shared schema.
        if name in shared_schemas:
            sf = shared_schemas[name]
            count_str = after_name[1:cb]
            count = -1 if count_str == "?" else int(count_str)
            if count == 0:
                return name, [], 1, None
            # Peek: if next line starts with @, it's expanded.
            use_shared = True
            next_idx = line_idx + 1
            ind = "  " * depth
            if next_idx < len(lines):
                nc = lines[next_idx]
                if depth > 0 and nc.startswith(ind):
                    nc = nc[len(ind):]
                if nc.lstrip().startswith("@"):
                    use_shared = False
            if use_shared:
                rows, consumed = _parse_tabular_body(lines, line_idx + 1, depth, sf, count)
                if count >= 0 and len(rows) != count:
                    raise ValueError(f"count_mismatch: declared {count}, got {len(rows)}")
                return name, rows, consumed + 1, None

        # No shared schema: standard parsing.
        arr, consumed = _parse_array_from_header(lines, line_idx, depth, after_name)
        return name, arr, consumed, None

    raise ValueError(f"invalid attachment form: {after_name}")


def _parse_tabular_body(
    lines: list[str], start: int, depth: int, fields: list[str], expected_count: int
) -> tuple[list[Any], int]:
    ind = "  " * depth
    rows: list[Any] = []
    i = start

    # Track inline schemas and shared array schemas.
    inline_schemas: dict[str, list[str]] = {}
    shared_array_schemas: dict[str, list[str]] = {}

    while i < len(lines):
        line = lines[i]
        if depth > 0 and not line.startswith(ind):
            break
        content = line[len(ind):] if depth > 0 else line
        if content.startswith("## ") or content.startswith("##!"):
            break
        if content and content[0] == " ":
            trimmed = content.lstrip()
            if trimmed.startswith("."):
                break
            break

        # Strip @N prefix (must be @digits).
        row_data = content
        row_has_id = False
        if row_data.startswith("@"):
            sp = row_data.find(" ")
            if sp > 0:
                id_str = row_data[1:sp]
                if id_str.isdigit():
                    row_data = row_data[sp + 1:]
                    row_has_id = True

        vals = split_respecting_quotes(row_data, "|")
        if len(vals) != len(fields):
            raise ValueError(f"row_width_mismatch: expected {len(fields)}, got {len(vals)}")

        # Parse cells.
        cell_values: dict[str, Any] = {}
        traditional_att_fields: list[str] = []
        inline_att_fields: list[str] = []
        inline_att_order: list[str] = []
        missing_fields: set[str] = set()

        for j, f in enumerate(fields):
            cell_val = vals[j]

            # Check for ^{fields} inline schema declaration.
            if cell_val.startswith("^{") and cell_val.endswith("}"):
                schema_str = cell_val[1:]
                ifs = split_field_decl(schema_str)
                inline_schemas[f] = ifs
                inline_att_fields.append(f)
                inline_att_order.append(f)
                continue

            parsed = parse_scalar(cell_val, tabular_context=True)
            if parsed is MISSING:
                missing_fields.add(f)
            elif parsed is ATTACHMENT:
                if f in inline_schemas:
                    inline_att_fields.append(f)
                    inline_att_order.append(f)
                else:
                    traditional_att_fields.append(f)
            else:
                cell_values[f] = parsed
        i += 1

        # Parse attachments in line order.
        all_att_fields = traditional_att_fields + inline_att_fields
        attachment_values: dict[str, Any] = {}

        if row_has_id and all_att_fields:
            inline_idx = 0

            while i < len(lines) and len(attachment_values) < len(all_att_fields):
                a_line = lines[i]
                a_content: str | None = None
                if a_line.startswith(ind + "  "):
                    a_content = a_line[len(ind) + 2:]
                elif depth == 0 or a_line.startswith(ind):
                    a_content = a_line[len(ind):] if depth > 0 else a_line
                else:
                    break
                if a_content is None:
                    break

                # Line starts with ".": traditional or prefixed inline.
                if a_content.startswith("."):
                    rest = a_content[1:]
                    att_name, after_name = _parse_attachment_name(rest)
                    after_name_stripped = after_name.lstrip()

                    # Prefixed inline data.
                    ifs = inline_schemas.get(att_name)
                    if ifs and not after_name_stripped.startswith("{}") and not after_name_stripped.startswith("["):
                        inline_vals = split_respecting_quotes(after_name_stripped, "|")
                        if len(inline_vals) != len(ifs):
                            raise ValueError(f"inline_width_mismatch: {att_name} expected {len(ifs)}, got {len(inline_vals)}")
                        obj: dict[str, Any] = {}
                        for k, inf in enumerate(ifs):
                            p = parse_scalar(inline_vals[k], tabular_context=True)
                            if p is not MISSING:
                                obj[inf] = p
                        attachment_values[att_name] = obj
                        i += 1
                        continue

                    # Traditional attachment.
                    att_name_t, att_val, consumed, parsed_fields = _parse_attachment(
                        lines, i, rest, depth + 2, shared_array_schemas
                    )
                    if not rows and parsed_fields:
                        shared_array_schemas[att_name_t] = parsed_fields
                    attachment_values[att_name_t] = att_val
                    i += consumed
                    continue

                # No-prefix line: positional inline data.
                found_inline = False
                next_inline_field = ""
                while inline_idx < len(inline_att_order):
                    candidate = inline_att_order[inline_idx]
                    if candidate not in attachment_values:
                        next_inline_field = candidate
                        found_inline = True
                        break
                    inline_idx += 1
                if not found_inline:
                    break

                ifs = inline_schemas[next_inline_field]
                inline_vals = split_respecting_quotes(a_content, "|")
                if len(inline_vals) != len(ifs):
                    raise ValueError(f"inline_width_mismatch: {next_inline_field} expected {len(ifs)}, got {len(inline_vals)}")
                obj = {}
                for k, inf in enumerate(ifs):
                    p = parse_scalar(inline_vals[k], tabular_context=True)
                    if p is not MISSING:
                        obj[inf] = p
                attachment_values[next_inline_field] = obj
                inline_idx += 1
                i += 1

            for f in all_att_fields:
                if f not in attachment_values:
                    raise ValueError(f"missing_attachment: {f}")

        if not row_has_id or not all_att_fields:
            att_indent = ind + "  "
            if i < len(lines) and lines[i].startswith(att_indent):
                peek = lines[i][len(att_indent):]
                if peek.startswith("."):
                    raise ValueError(f"orphan_attachment: {peek}")

        row: dict[str, Any] = {}
        for f in fields:
            if f in missing_fields:
                continue
            if f in cell_values:
                row[f] = cell_values[f]
            elif f in attachment_values:
                row[f] = attachment_values[f]
        rows.append(row)

        if expected_count >= 0 and len(rows) >= expected_count:
            break

    return rows, i - start


def _parse_attachment(
    lines: list[str], line_idx: int, rest: str, depth: int
) -> tuple[str, Any, int]:
    if rest and rest[0] == '"':
        close_idx = -1
        j = 1
        while j < len(rest):
            if rest[j] == "\\":
                j += 2
                continue
            if rest[j] == '"':
                close_idx = j
                break
            j += 1
        if close_idx < 0:
            raise ValueError("unterminated_quote")
        name = parse_quoted_string(rest[:close_idx + 1])
        after_name = rest[close_idx + 1:].lstrip()
    else:
        sp = rest.find(" ")
        if sp < 0:
            raise ValueError(f"invalid attachment: {rest}")
        name = rest[:sp]
        after_name = rest[sp:].lstrip()

    if after_name.startswith("{}"):
        nested: dict[str, Any] = {}
        consumed = _parse_object_body(lines, line_idx + 1, depth, nested)
        return name, nested, consumed + 1
    if after_name.startswith("["):
        arr, consumed = _parse_array_from_header(lines, line_idx, depth, after_name)
        return name, arr, consumed
    raise ValueError(f"invalid attachment form: {after_name}")


def _parse_expanded_body(
    lines: list[str], start: int, depth: int
) -> tuple[list[Any], int]:
    ind = "  " * depth
    items: list[Any] = []
    i = start

    while i < len(lines):
        line = lines[i]
        if depth > 0 and not line.startswith(ind):
            break
        content = line[len(ind):] if depth > 0 else line
        if content.startswith("## ") or content.startswith("##!"):
            break
        if not content.startswith("@"):
            break
        sp = content.find(" ")
        if sp < 0:
            break

        id_str = content[1:sp]
        try:
            item_id = int(id_str)
            if item_id != len(items):
                raise ValueError(f"invalid_item_id: expected @{len(items)}, got @{id_str}")
        except ValueError as e:
            if "invalid_item_id" in str(e):
                raise

        marker = content[sp + 1:]

        if marker.startswith("="):
            items.append(parse_scalar(marker[1:]))
            i += 1
            continue
        if marker.startswith("{}"):
            nested: dict[str, Any] = {}
            i += 1
            consumed = _parse_object_body(lines, i, depth + 1, nested)
            items.append(nested)
            i += consumed
            continue
        if marker.startswith("["):
            arr, consumed = _parse_array_from_header(lines, i, depth + 1, marker)
            items.append(arr)
            i += consumed
            continue
        break

    return items, i - start


def _parse_count(s: str) -> int:
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


def _validate_summary_counts(
    summary_line: str, deferred_count: int, content_lines: list[str]
) -> None:
    counts_str = ""
    for p in summary_line.split():
        if p.startswith("counts="):
            counts_str = p[7:]
            break
    if not counts_str:
        return
    count_vals = counts_str.split(",")
    if len(count_vals) != deferred_count:
        raise ValueError(
            f"count_mismatch: summary has {len(count_vals)} count entries "
            f"but {deferred_count} deferred sections"
        )
    actual_counts: list[int] = []
    in_deferred = False
    current_count = 0
    for line in content_lines:
        trimmed = line.lstrip()
        if trimmed.startswith("## ") and "[?]" in trimmed:
            if in_deferred:
                actual_counts.append(current_count)
            in_deferred = True
            current_count = 0
            continue
        if trimmed.startswith("## "):
            if in_deferred:
                actual_counts.append(current_count)
                in_deferred = False
            continue
        if in_deferred and not trimmed.startswith(" ") and not trimmed.startswith("."):
            current_count += 1
    if in_deferred:
        actual_counts.append(current_count)
    for idx, cv in enumerate(count_vals):
        try:
            declared = int(cv)
        except ValueError:
            raise ValueError(f"count_mismatch: invalid count value '{cv}'")
        if idx < len(actual_counts) and declared != actual_counts[idx]:
            raise ValueError(
                f"count_mismatch: section {idx} declared {declared} in summary, "
                f"actual {actual_counts[idx]}"
            )
