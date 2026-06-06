"""GCF generic decoder: parses any GCF text (tabular or graph) back to Python objects."""

from __future__ import annotations

from typing import Any

from .decode import decode


def decode_generic(input_text: str) -> Any:
    """Decode any GCF text back into Python objects.

    Handles tabular arrays, key-value pairs, nested sections, inline
    primitive arrays, and graph profile payloads.

    Returns dicts, lists, and primitives matching the original structure.
    """
    input_text = input_text.rstrip("\n\r")
    if not input_text:
        return None

    lines = input_text.split("\n")

    # Graph profile fallback.
    if lines[0].startswith("GCF "):
        p = decode(input_text)
        return {
            "tool": p.tool,
            "tokenBudget": p.token_budget,
            "tokensUsed": p.tokens_used,
            "packRoot": p.pack_root,
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
                    **({"status": e.status} if e.status else {}),
                }
                for e in p.edges
            ],
        }

    result: dict[str, Any] = {}
    _parse_object(lines, 0, 0, result)
    return result


def _parse_object(lines: list[str], start: int, depth: int, out: dict[str, Any]) -> int:
    indent = "  " * depth
    i = start

    while i < len(lines):
        raw = lines[i].rstrip("\r")
        if raw == "" or raw.startswith("# "):
            i += 1
            continue

        if depth > 0 and not raw.startswith(indent):
            break

        content = raw[len(indent):] if depth > 0 else raw

        if content.startswith("## _summary"):
            i += 1
            continue

        if content.startswith("## "):
            header = content[3:]
            bracket_idx = header.find(" [")

            if bracket_idx >= 0:
                name = header[:bracket_idx]
                rest = header[bracket_idx + 2:]
                close_bracket = rest.find("]")

                if close_bracket >= 0:
                    after_bracket = rest[close_bracket + 1:]

                    if after_bracket.startswith("{"):
                        field_end = after_bracket.find("}")
                        if field_end >= 0:
                            fields = after_bracket[1:field_end].split(",")
                            i += 1
                            rows, consumed = _parse_tabular_rows(lines, i, depth, fields)
                            out[name] = rows
                            i += consumed
                            continue
                    else:
                        count_str = rest[:close_bracket]
                        if count_str == "0":
                            out[name] = []
                            i += 1
                            continue
                        i += 1
                        items, consumed = _parse_non_uniform_array(lines, i, depth)
                        out[name] = items
                        i += consumed
                        continue

            name = header
            bi = name.find(" [")
            if bi >= 0:
                name = name[:bi]
            i += 1
            nested: dict[str, Any] = {}
            consumed = _parse_object(lines, i, depth + 1, nested)
            out[name] = nested
            i += consumed
            continue

        # Inline primitive array.
        bracket_idx = content.find("[")
        if bracket_idx > 0:
            colon_idx = content.find("]: ")
            if colon_idx > bracket_idx:
                name = content[:bracket_idx]
                vals_str = content[colon_idx + 3:]
                out[name] = [_parse_value(v.strip()) for v in vals_str.split(",")]
                i += 1
                continue

        # Key=value.
        eq_idx = content.find("=")
        if eq_idx > 0:
            key = content[:eq_idx]
            val = content[eq_idx + 1:]
            out[key] = _parse_value(val)
            i += 1
            continue

        i += 1

    return i - start


def _parse_tabular_rows(
    lines: list[str], start: int, depth: int, fields: list[str]
) -> tuple[list[Any], int]:
    indent = "  " * depth
    rows: list[Any] = []
    i = start

    while i < len(lines):
        raw = lines[i].rstrip("\r")
        if raw == "":
            i += 1
            continue

        if depth > 0 and not raw.startswith(indent):
            break
        content = raw[len(indent):] if depth > 0 else raw

        if content.startswith("## "):
            break
        if content.startswith("# "):
            i += 1
            continue

        row_data = content
        has_nested = False
        if row_data.startswith("@"):
            sp = row_data.find(" ")
            if sp > 0:
                row_data = row_data[sp + 1:]
                has_nested = True

        vals = row_data.split("|")
        row: dict[str, Any] = {}
        for j, f in enumerate(fields):
            row[f] = _parse_value(vals[j]) if j < len(vals) else None

        i += 1

        if has_nested:
            nested_indent = indent + "  "
            while i < len(lines):
                nl = lines[i].rstrip("\r")
                if not nl.startswith(nested_indent):
                    break
                nc = nl[len(nested_indent):]

                if nc.startswith("."):
                    field_name = nc[1:]
                    i += 1
                    nested: dict[str, Any] = {}
                    consumed = _parse_object(lines, i, depth + 2, nested)
                    row[field_name] = nested
                    i += consumed
                else:
                    break

        rows.append(row)

    return rows, i - start


def _parse_non_uniform_array(
    lines: list[str], start: int, depth: int
) -> tuple[list[Any], int]:
    indent = "  " * depth
    items: list[Any] = []
    i = start

    while i < len(lines):
        raw = lines[i].rstrip("\r")
        if raw == "":
            i += 1
            continue
        if depth > 0 and not raw.startswith(indent):
            break
        content = raw[len(indent):] if depth > 0 else raw
        if content.startswith("## "):
            break

        if content.startswith("@"):
            sp = content.find(" ")
            if sp > 0:
                items.append(_parse_value(content[sp + 1:]))
            i += 1
        else:
            break

    return items, i - start


def _parse_value(s: str) -> Any:
    if s == "-":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s == '""':
        return ""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s
