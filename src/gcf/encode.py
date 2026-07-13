"""GCF encoder: serializes Payload into GCF text format."""

from __future__ import annotations

from .constants import KIND_ABBREV
from .types import Payload, Symbol


def encode(p: Payload) -> str:
    """Encode a Payload into GCF text format.

    Args:
        p: The payload to encode.

    Returns:
        GCF-formatted text string.
    """
    parts: list[str] = []

    # Group symbols by distance (sorted by score descending within each group),
    # then assign local IDs in output order so they are sequential in the wire
    # (SPEC 16.1).
    groups = _group_by_distance(p.symbols)
    sym_index: dict[str, int] = {}
    next_id = 0
    for _distance, g_symbols in groups:
        for s in g_symbols:
            sym_index[s.qualified_name] = next_id
            next_id += 1

    # Count valid edges (both endpoints in symbol index).
    valid_edges = sum(
        1 for e in p.edges
        if e.source in sym_index and e.target in sym_index
    )

    # Header line (SPEC 16.1): omit budget/tokens/edges when zero, matching the
    # reference encoder.
    header = f"GCF profile=graph tool={p.tool}"
    if p.token_budget > 0:
        header += f" budget={p.token_budget}"
    if p.tokens_used > 0:
        header += f" tokens={p.tokens_used}"
    header += f" symbols={len(p.symbols)}"
    if valid_edges > 0:
        header += f" edges={valid_edges}"
    if p.pack_root:
        header += f" pack_root={p.pack_root}"
    parts.append(header)

    group_names = ["targets", "related", "extended"]

    for g_distance, g_symbols in groups:
        if not g_symbols:
            continue
        if g_distance < len(group_names):
            name = group_names[g_distance]
        else:
            name = f"distance_{g_distance}"
        parts.append(f"## {name}")

        for s in g_symbols:
            idx = sym_index[s.qualified_name]
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"@{idx} {kind} {s.qualified_name} {s.score:.2f} {s.provenance}")

    # Edges section. Order edges by source ID then target ID (then edge type
    # for parallel edges) so the wire is canonical regardless of the order
    # edges were provided (SPEC 16.1). Edge reordering is decode-invariant
    # (edges are a set) and does not affect pack_root, which sorts edge records
    # independently.
    if p.edges:
        resolved: list[tuple[int, int, str, str]] = []
        for e in p.edges:
            src_idx = sym_index.get(e.source)
            tgt_idx = sym_index.get(e.target)
            if src_idx is None or tgt_idx is None:
                continue
            resolved.append((src_idx, tgt_idx, e.edge_type, e.status))
        resolved.sort(key=lambda r: (r[0], r[1], r[2]))
        edge_lines: list[str] = []
        for src_idx, tgt_idx, edge_type, status in resolved:
            line = f"@{tgt_idx}<@{src_idx} {edge_type}"
            if status and status != "unchanged":
                line += f" {status}"
            edge_lines.append(line)
        parts.append(f"## edges [{len(edge_lines)}]")
        parts.extend(edge_lines)

    return "\n".join(parts) + "\n"


def _group_by_distance(symbols: list[Symbol]) -> list[tuple[int, list[Symbol]]]:
    """Group symbols by distance ascending, sorted by score descending within each
    group (stable), matching the reference encoder so IDs are assigned canonically."""
    if not symbols:
        return []

    ordered = sorted(symbols, key=lambda s: (s.distance, -s.score))
    groups: list[tuple[int, list[Symbol]]] = []
    current_distance: int | None = None
    current_symbols: list[Symbol] = []

    for s in ordered:
        if current_distance is None or current_distance != s.distance:
            if current_symbols:
                groups.append((current_distance, current_symbols))  # type: ignore[arg-type]
            current_distance = s.distance
            current_symbols = [s]
        else:
            current_symbols.append(s)

    if current_symbols:
        groups.append((current_distance, current_symbols))  # type: ignore[arg-type]

    return groups
