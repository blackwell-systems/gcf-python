"""GCF encoder: serializes Payload into GCF text format."""

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

    # Header line.
    header = f"GCF tool={p.tool} budget={p.token_budget} tokens={p.tokens_used} symbols={len(p.symbols)}"
    if p.pack_root:
        header += f" pack_root={p.pack_root}"
    parts.append(header)

    # Build symbol index for edge references.
    sym_index: dict[str, int] = {}
    for i, s in enumerate(p.symbols):
        sym_index[s.qualified_name] = i

    # Group symbols by distance.
    groups = _group_by_distance(p.symbols)
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

    # Edges section.
    if p.edges:
        edge_lines: list[str] = []
        for e in p.edges:
            src_idx = sym_index.get(e.source)
            tgt_idx = sym_index.get(e.target)
            if src_idx is None or tgt_idx is None:
                continue
            line = f"@{tgt_idx}<@{src_idx} {e.edge_type}"
            if e.status and e.status != "unchanged":
                line += f" {e.status}"
            edge_lines.append(line)
        if edge_lines:
            parts.append("## edges")
            parts.extend(edge_lines)

    return "\n".join(parts) + "\n"


def _group_by_distance(symbols: list[Symbol]) -> list[tuple[int, list[Symbol]]]:
    """Group symbols by distance, preserving order."""
    if not symbols:
        return []

    groups: list[tuple[int, list[Symbol]]] = []
    current_distance: int | None = None
    current_symbols: list[Symbol] = []

    for s in symbols:
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
