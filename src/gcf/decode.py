"""GCF decoder: parses GCF text back into a Payload."""

from __future__ import annotations

from .constants import KIND_EXPAND
from .types import Edge, Payload, Symbol


class DecodeError(Exception):
    """Raised when GCF text cannot be parsed."""


def decode(input_text: str) -> Payload:
    """Parse GCF text back into a Payload.

    Args:
        input_text: GCF-formatted text string.

    Returns:
        Parsed Payload.

    Raises:
        DecodeError: If the input is not valid GCF.
    """
    lines = input_text.split("\n")
    if not lines:
        raise DecodeError("empty input")

    p = Payload()

    # Parse header.
    header = lines[0]
    if not header.startswith("GCF "):
        raise DecodeError(f"invalid header, expected 'GCF ...' got {header!r}")
    _parse_header(header[4:], p)

    if not p.tool:
        raise DecodeError("missing_tool: header missing required 'tool' field")

    # Detect delta mode.
    is_delta = "delta=true" in header
    valid_delta_sections = {"removed", "added", "edges_removed", "edges_added"}

    # Parse body: symbols and edges.
    symbols: list[Symbol] = []
    sym_by_id: dict[int, Symbol] = {}
    current_distance = 0
    in_edges = False

    for line in lines[1:]:
        line = line.rstrip("\r")
        if not line:
            continue

        # Skip ##! summary trailer.
        if line.startswith("##! "):
            continue

        # Group header.
        if line.startswith("## "):
            group = line[3:]
            # Strip bracket suffix: "edges [200]" -> "edges"
            bracket_idx = group.find(" [")
            if bracket_idx >= 0:
                group = group[:bracket_idx]
            if is_delta and group not in valid_delta_sections:
                raise DecodeError(f"malformed_delta: invalid delta section {group!r}")
            in_edges = group == "edges"
            if not in_edges:
                if group == "targets":
                    current_distance = 0
                elif group == "related":
                    current_distance = 1
                elif group == "extended":
                    current_distance = 2
                elif group.startswith("distance_"):
                    try:
                        current_distance = int(group[9:])
                    except ValueError:
                        pass
            continue

        # Comment.
        if line.startswith("# "):
            continue

        if in_edges:
            edge = _parse_edge_line(line, sym_by_id)
            p.edges.append(edge)
        else:
            sym, sym_id = _parse_symbol_line(line, current_distance)
            symbols.append(sym)
            sym_by_id[sym_id] = sym

    p.symbols = symbols
    return p


def _parse_header(fields: str, p: Payload) -> None:
    """Parse header key=value pairs into the payload."""
    for part in fields.split():
        kv = part.split("=", 1)
        if len(kv) != 2:
            continue
        key, value = kv
        if key == "tool":
            p.tool = value
        elif key == "budget":
            try:
                p.token_budget = int(value)
            except ValueError as e:
                raise DecodeError(f"invalid budget {value!r}: {e}") from e
        elif key == "tokens":
            try:
                p.tokens_used = int(value)
            except ValueError as e:
                raise DecodeError(f"invalid tokens {value!r}: {e}") from e
        elif key == "pack_root":
            p.pack_root = value
        # "symbols" is informational, reconstructed from parsed symbols.


def _parse_symbol_line(line: str, distance: int) -> tuple[Symbol, int]:
    """Parse a symbol line into a Symbol and its local ID."""
    if not line.startswith("@"):
        raise DecodeError(f"invalid_node_line: expected symbol line starting with @, got {line!r}")

    parts = line.split()
    if len(parts) < 5:
        raise DecodeError(
            f"invalid_node_line: symbol line needs at least 5 fields, got {len(parts)} in {line!r}"
        )

    id_str = parts[0][1:]  # strip @
    try:
        sym_id = int(id_str)
    except ValueError as e:
        raise DecodeError(f"invalid_symbol_id: invalid symbol id {id_str!r}: {e}") from e

    kind = parts[1]
    kind = KIND_EXPAND.get(kind, kind)

    qname = parts[2]

    try:
        score = float(parts[3])
    except ValueError as e:
        raise DecodeError(f"invalid_score: invalid score {parts[3]!r}: {e}") from e

    provenance = parts[4]

    return Symbol(
        qualified_name=qname,
        kind=kind,
        score=score,
        provenance=provenance,
        distance=distance,
    ), sym_id


def _parse_edge_line(line: str, sym_by_id: dict[int, Symbol]) -> Edge:
    """Parse an edge line into an Edge."""
    parts = line.split()
    if len(parts) < 2:
        raise DecodeError(f"edge line needs at least 2 fields, got {line!r}")

    ref = parts[0]
    lt_idx = ref.find("<")
    if lt_idx < 0:
        raise DecodeError(f"invalid_edge_syntax: edge line missing '<' separator in {ref!r}")

    target_id_str = ref[1:lt_idx]  # strip leading @
    source_id_str = ref[lt_idx + 2:]  # strip <@

    try:
        target_id = int(target_id_str)
    except ValueError as e:
        raise DecodeError(f"invalid target id {target_id_str!r}: {e}") from e

    try:
        source_id = int(source_id_str)
    except ValueError as e:
        raise DecodeError(f"invalid source id {source_id_str!r}: {e}") from e

    target_sym = sym_by_id.get(target_id)
    source_sym = sym_by_id.get(source_id)
    if target_sym is None or source_sym is None:
        raise DecodeError(
            f"unknown_edge_reference: edge references unknown symbol id(s): target={target_id} source={source_id}"
        )

    edge_type = parts[1]
    status = parts[2] if len(parts) >= 3 else ""

    return Edge(
        source=source_sym.qualified_name,
        target=target_sym.qualified_name,
        edge_type=edge_type,
        status=status,
    )
