"""GCF generic-profile delta encoding (SPEC Section 10a).

Producer + consumer. Mirrors the gcf-go reference implementation; the shared
conformance fixtures (generic-pack-root/, generic-delta/) hold both to identical
bytes and hashes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .scalar import (
    format_key,
    format_number,
    format_scalar,
    parse_scalar,
    quote_string,
    split_respecting_quotes,
)


@dataclass
class GenericSet:
    """A keyed record set: the unit generic-profile delta operates on (Section 10a).

    Rows are order-agnostic (set semantics); ``fields`` carries the declared column
    order for the wire form; ``key`` names the identity column (the ``@id`` / ``key=``);
    ``name`` is the tabular section name for a full payload.
    """

    key: str
    fields: list[str]
    rows: list[dict[str, Any]]
    name: str = "rows"


@dataclass
class GenericDeltaPayload:
    key: str
    fields: list[str]
    base_root: str = ""
    new_root: str = ""
    added: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    removed: list[Any] = field(default_factory=list)
    tool: str = ""
    delta_tokens: int = 0
    full_tokens: int = 0


def _canonical_cell(v: Any) -> str:
    """Canonicalize one value for the pack-root record (Section 10a.3).

    Decoupled from the wire cell encoder: collision-free and record-safe, not
    round-trippable. Typed literals stay bare (null is ``-``, booleans true/false,
    numbers canonical); strings are ALWAYS quoted so they cannot collide with a
    typed literal and any tab/newline inside is escaped.
    """
    if v is None:
        return "-"
    if isinstance(v, bool):  # must precede int: bool is a subclass of int
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return format_number(float(v))
    if isinstance(v, str):
        return quote_string(v)
    return quote_string(str(v))


def generic_pack_root(s: GenericSet) -> str:
    """Canonical pack root for a keyed set (gcf-pack-root-v1, generic profile, 10a.3).

    Records and fields are sorted by unsigned UTF-8 byte order to match every SDK.
    """
    sorted_fields = sorted(s.fields, key=lambda x: x.encode("utf-8"))
    records: list[str] = []
    for row in s.rows:
        parts = ["R"]
        for f in sorted_fields:
            parts.append(f)
            parts.append(_canonical_cell(row.get(f)))
        records.append("\t".join(parts) + "\n")
    records.sort(key=lambda r: r.encode("utf-8"))
    digest = hashlib.sha256("".join(records).encode("utf-8")).hexdigest()
    return "sha256:" + digest


def _index_by_key(s: GenericSet) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    for row in s.rows:
        ident = _canonical_cell(row.get(s.key))
        if ident in m:
            raise ValueError(f"delta_invalid: duplicate identity {ident} for key {s.key!r}")
        m[ident] = row
    return m


def _rows_equal(a: dict[str, Any], b: dict[str, Any], fields: list[str]) -> bool:
    return all(_canonical_cell(a.get(f)) == _canonical_cell(b.get(f)) for f in fields)


def diff_generic_sets(base: GenericSet, nxt: GenericSet) -> GenericDeltaPayload:
    """Compute the delta from ``base`` to ``nxt`` (the blessed producer path).

    Centralizes the keyed-diff invariants: identity uniqueness, added-not-in-base,
    changed-must-exist, whole-row replacement, unchanged rows omitted. Output is
    sorted by identity for reproducibility (10a.6). Schema change or a missing key
    raises (caller must send full, 10a.7).
    """
    if not nxt.key:
        raise ValueError("delta_invalid: no identity key")
    if nxt.key != base.key or list(base.fields) != list(nxt.fields):
        raise ValueError("delta_invalid: schema change (send full)")

    base_by_id = _index_by_key(base)
    next_by_id = _index_by_key(nxt)

    d = GenericDeltaPayload(
        key=nxt.key,
        fields=list(nxt.fields),
        base_root=generic_pack_root(base),
        new_root=generic_pack_root(nxt),
    )
    for ident, row in next_by_id.items():
        brow = base_by_id.get(ident)
        if brow is None:
            d.added.append(row)
        elif not _rows_equal(brow, row, nxt.fields):
            d.changed.append(row)
        # equal rows are omitted (silence = "keep it", 10a.5)
    for ident, brow in base_by_id.items():
        if ident not in next_by_id:
            d.removed.append(brow.get(nxt.key))

    d.added.sort(key=lambda r: _canonical_cell(r.get(d.key)))
    d.changed.sort(key=lambda r: _canonical_cell(r.get(d.key)))
    d.removed.sort(key=_canonical_cell)
    return d


def _field_decl(fields: list[str], key: str) -> str:
    return ",".join(("@" + format_key(f)) if f == key else format_key(f) for f in fields)


def _encode_row(row: dict[str, Any], fields: list[str]) -> str:
    return "|".join(format_scalar(row.get(f), "|") for f in fields)


def encode_generic_full(s: GenericSet, tool: str = "") -> str:
    """Emit a delta-participating full base payload: key= header, @id field, rows."""
    name = s.name or "rows"
    header = "GCF profile=generic"
    if tool:
        header += f" tool={tool}"
    header += f" pack_root={generic_pack_root(s)} key={s.key}"
    lines = [header, f"## {name} [{len(s.rows)}]{{{_field_decl(s.fields, s.key)}}}"]
    lines += [_encode_row(row, s.fields) for row in s.rows]
    return "\n".join(lines) + "\n"


def encode_generic_delta(d: GenericDeltaPayload) -> str:
    """Serialize a delta payload (10a.2). Sections ordered added/changed/removed."""
    header = "GCF profile=generic"
    if d.tool:
        header += f" tool={d.tool}"
    header += f" delta=true base_root={d.base_root} new_root={d.new_root} key={d.key}"
    if d.full_tokens > 0:
        savings = 100.0 * (1.0 - d.delta_tokens / d.full_tokens)
        header += f" savings={savings:.0f}%"
    lines = [header]
    if d.added:
        lines.append(f"## added [{len(d.added)}]{{{_field_decl(d.fields, d.key)}}}")
        lines += [_encode_row(r, d.fields) for r in d.added]
    if d.changed:
        lines.append(f"## changed [{len(d.changed)}]{{{_field_decl(d.fields, d.key)}}}")
        lines += [_encode_row(r, d.fields) for r in d.changed]
    if d.removed:
        lines.append(f"## removed [{len(d.removed)}]{{@{d.key}}}")
        lines += [format_scalar(idv, "|") for idv in d.removed]
    return "\n".join(lines) + "\n"


def verify_generic_delta(base: GenericSet, d: GenericDeltaPayload, expected_new_root: str) -> GenericSet:
    """Apply a delta to a base set and verify the result hashes to expected_new_root.

    Atomic (10a.5): the whole payload is validated before any mutation; on failure the
    base is left untouched and a ValueError is raised.
    """
    if generic_pack_root(base) != d.base_root:
        raise ValueError("base_mismatch: base root does not equal delta base_root")
    base_by_id = _index_by_key(base)

    for idv in d.removed:
        if _canonical_cell(idv) not in base_by_id:
            raise ValueError(f"delta_invalid: removing identity {_canonical_cell(idv)} not in base")
    for row in d.added:
        if _canonical_cell(row.get(d.key)) in base_by_id:
            raise ValueError(f"delta_invalid: adding identity {_canonical_cell(row.get(d.key))} that already exists")
    for row in d.changed:
        if _canonical_cell(row.get(d.key)) not in base_by_id:
            raise ValueError(f"delta_invalid: changing identity {_canonical_cell(row.get(d.key))} not in base")

    work = dict(base_by_id)
    for idv in d.removed:
        work.pop(_canonical_cell(idv), None)
    for row in d.added:
        work[_canonical_cell(row.get(d.key))] = row
    for row in d.changed:
        work[_canonical_cell(row.get(d.key))] = row

    result = GenericSet(key=base.key, fields=list(base.fields), rows=list(work.values()), name=base.name)
    got = generic_pack_root(result)
    if got != expected_new_root:
        raise ValueError(f"root_mismatch: computed {got}, expected {expected_new_root}")
    return result


# --- consumer-side wire parsing ---


def _parse_header_fields(header: str) -> dict[str, str]:
    m: dict[str, str] = {}
    for tok in header.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            if k:
                m[k] = v
    return m


def _parse_count(s: str) -> int:
    if s == "0":
        return 0
    if not s or s[0] == "0" or not s.isdigit():
        raise ValueError(f"invalid_count: {s}")
    return int(s)


def _split_delta_field_decl(decl: str) -> tuple[list[str], str]:
    if len(decl) < 2 or decl[0] != "{" or decl[-1] != "}":
        raise ValueError(f"invalid field declaration: {decl}")
    inner = decl[1:-1]
    if inner == "":
        return [], ""
    fields: list[str] = []
    key_field = ""
    for raw in split_respecting_quotes(inner, ","):
        f = raw.strip()
        is_key = False
        if f.startswith("@"):
            f = f[1:]
            is_key = True
        if len(f) >= 2 and f[0] == '"' and f[-1] == '"':
            from .scalar import parse_quoted_string

            f = parse_quoted_string(f)
        if is_key:
            key_field = f
        fields.append(f)
    return fields, key_field


def _parse_section_header(content: str) -> tuple[str, int, list[str], str]:
    bi = content.find(" [")
    if bi < 0:
        raise ValueError(f"delta_invalid: section header without count: {content!r}")
    name = content[:bi].strip()
    rest = content[bi + 1:]  # "[N]{...}"
    if not rest or rest[0] != "[":
        raise ValueError(f"delta_invalid: malformed section header: {content!r}")
    close = rest.find("]")
    if close < 0:
        raise ValueError(f"delta_invalid: unterminated count: {content!r}")
    count = _parse_count(rest[1:close])
    fields, key_field = _split_delta_field_decl(rest[close + 1:])
    return name, count, fields, key_field


def _parse_row(line: str, fields: list[str]) -> dict[str, Any]:
    cells = split_respecting_quotes(line, "|")
    if len(cells) != len(fields):
        raise ValueError(f"delta_invalid: row has {len(cells)} cells, expected {len(fields)}: {line!r}")
    return {f: parse_scalar(cells[i], True) for i, f in enumerate(fields)}


def decode_generic_full(text: str) -> tuple[GenericSet, str]:
    """Parse a delta-participating full base payload into (GenericSet, pack_root)."""
    lines = text.rstrip("\n").split("\n")
    if not lines:
        raise ValueError("empty payload")
    hdr = _parse_header_fields(lines[0])
    if hdr.get("profile") != "generic":
        raise ValueError("not a generic payload")
    s = GenericSet(key=hdr.get("key", ""), fields=[], rows=[])
    i = 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith("## "):
            i += 1
            continue
        name, count, fields, key_field = _parse_section_header(line[3:])
        s.name, s.fields = name, fields
        if not s.key:
            s.key = key_field
        i += 1
        for _ in range(count):
            if i >= len(lines):
                raise ValueError("delta_invalid: fewer rows than declared count")
            s.rows.append(_parse_row(lines[i], fields))
            i += 1
    return s, hdr.get("pack_root", "")


def decode_generic_delta(text: str) -> GenericDeltaPayload:
    """Parse a delta payload (10a.2) into a GenericDeltaPayload for application."""
    lines = text.rstrip("\n").split("\n")
    if not lines:
        raise ValueError("empty payload")
    hdr = _parse_header_fields(lines[0])
    if hdr.get("profile") != "generic":
        raise ValueError("not a generic payload")
    if hdr.get("delta") != "true":
        raise ValueError("not a delta payload")
    d = GenericDeltaPayload(
        key=hdr.get("key", ""),
        fields=[],
        base_root=hdr.get("base_root", ""),
        new_root=hdr.get("new_root", ""),
        tool=hdr.get("tool", ""),
    )
    i = 1
    while i < len(lines):
        line = lines[i]
        if not line.startswith("## "):
            i += 1
            continue
        name, count, fields, key_field = _parse_section_header(line[3:])
        if not d.key and key_field:
            d.key = key_field
        if not d.fields and name in ("added", "changed"):
            d.fields = fields
        i += 1
        if name in ("added", "changed"):
            rows = []
            for _ in range(count):
                if i >= len(lines):
                    raise ValueError(f"delta_invalid: fewer rows than declared count in ## {name}")
                rows.append(_parse_row(lines[i], fields))
                i += 1
            if name == "added":
                d.added = rows
            else:
                d.changed = rows
        elif name == "removed":
            for _ in range(count):
                if i >= len(lines):
                    raise ValueError("delta_invalid: fewer identities than declared count in ## removed")
                d.removed.append(parse_scalar(lines[i], True))
                i += 1
        else:
            raise ValueError(f"delta_invalid: unknown delta section {name!r}")
    return d
