"""GCF delta encoding: only added/removed symbols for incremental delivery."""

from .constants import KIND_ABBREV, KIND_EXPAND
from .packroot import pack_root
from .types import DeltaPayload, Edge, Symbol


def encode_delta(d: DeltaPayload) -> str:
    """Encode a DeltaPayload into GCF delta format.

    Args:
        d: The delta payload to encode.

    Returns:
        GCF delta-formatted text string.
    """
    parts: list[str] = []

    # Header.
    savings = 0.0
    if d.full_tokens > 0:
        savings = 100.0 * (1.0 - d.delta_tokens / d.full_tokens)

    parts.append(
        f"GCF profile=graph tool={d.tool} delta=true base_root={d.base_root} "
        f"new_root={d.new_root} tokens={d.delta_tokens} savings={savings:.0f}%"
    )

    # Removed symbols: short references (consumer already has the full declaration).
    if d.removed:
        parts.append("## removed")
        for s in d.removed:
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(f"{kind} {s.qualified_name}")

    # Added symbols: full declarations (consumer doesn't have these).
    if d.added:
        parts.append("## added")
        for i, s in enumerate(d.added):
            kind = KIND_ABBREV.get(s.kind, s.kind)
            parts.append(
                f"@{i} {kind} {s.qualified_name} {s.score:.2f} {s.provenance} {s.distance}"
            )

    # Removed edges.
    if d.removed_edges:
        parts.append("## edges_removed")
        for e in d.removed_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    # Added edges.
    if d.added_edges:
        parts.append("## edges_added")
        for e in d.added_edges:
            parts.append(f"{e.source} -> {e.target} {e.edge_type}")

    return "\n".join(parts) + "\n"


def _expand_kind(k: str) -> str:
    """Reverse a kind abbreviation to its full form (identity if unknown)."""
    return KIND_EXPAND.get(k, k)


def _parse_delta_edge(line: str) -> Edge:
    """Parse a `source -> target type` delta edge line."""
    idx = line.find(" -> ")
    if idx < 0:
        raise ValueError(f"malformed_delta: edge line missing ' -> ': {line!r}")
    source = line[:idx]
    rest = line[idx + 4 :].split()
    if len(rest) != 2:
        raise ValueError(
            f"malformed_delta: edge line {line!r} must be 'source -> target type'"
        )
    return Edge(source=source, target=rest[0], edge_type=rest[1])


def decode_delta(wire: str) -> DeltaPayload:
    """Parse a GCF graph delta wire payload back into a DeltaPayload.

    Kind abbreviations on removed/added lines are expanded to their full form so the
    result matches a base snapshot's symbol identities. Raises ValueError containing
    ``malformed_delta`` on bad lines or unknown sections.
    """
    lines = wire.rstrip("\n").split("\n")
    if not lines or lines[0] == "":
        raise ValueError("missing_header: empty delta payload")
    header = lines[0].rstrip("\r")
    if not header.startswith("GCF profile=graph"):
        raise ValueError(
            "missing_profile: delta header must begin with 'GCF profile=graph'"
        )

    d = DeltaPayload()
    for field in header.split():
        kv = field.split("=", 1)
        if len(kv) != 2:
            continue
        key, value = kv
        if key == "tool":
            d.tool = value
        elif key == "base_root":
            d.base_root = value
        elif key == "new_root":
            d.new_root = value

    section = ""
    for raw in lines[1:]:
        line = raw.rstrip("\r")
        if line == "":
            continue
        if line.startswith("## "):
            section = line[3:].strip()
            if section not in ("removed", "added", "edges_removed", "edges_added"):
                raise ValueError(f"malformed_delta: unknown section {section!r}")
            continue
        if section == "removed":
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(
                    f"malformed_delta: removed line {line!r} must be 'kind qname'"
                )
            d.removed.append(
                Symbol(kind=_expand_kind(parts[0]), qualified_name=parts[1])
            )
        elif section == "added":
            parts = line.split()
            if len(parts) != 6:
                raise ValueError(
                    f"malformed_delta: added line {line!r} must be "
                    "'@id kind qname score provenance distance'"
                )
            try:
                score = float(parts[3])
            except ValueError:
                raise ValueError(f"malformed_delta: invalid added score {parts[3]!r}")
            try:
                dist = int(parts[5])
            except ValueError:
                raise ValueError(
                    f"malformed_delta: invalid added distance {parts[5]!r}"
                )
            d.added.append(
                Symbol(
                    kind=_expand_kind(parts[1]),
                    qualified_name=parts[2],
                    score=score,
                    provenance=parts[4],
                    distance=dist,
                )
            )
        elif section in ("edges_removed", "edges_added"):
            e = _parse_delta_edge(line)
            if section == "edges_removed":
                d.removed_edges.append(e)
            else:
                d.added_edges.append(e)
        else:
            raise ValueError(
                f"malformed_delta: data line {line!r} before any section header"
            )
    return d


def verify_delta(
    base_symbols: list[Symbol],
    base_edges: list[Edge],
    removed: list[Symbol],
    added: list[Symbol],
    removed_edges: list[Edge],
    added_edges: list[Edge],
    expected_new_root: str,
) -> tuple[list[Symbol], list[Edge]]:
    """Apply a delta to a base snapshot and verify the resulting pack root.

    Symbols are matched by identity ``(kind, qualified_name)``; edges by
    ``(source, target, edge_type)``. Raises ValueError containing ``delta_invalid``
    when removing a symbol/edge that does not exist or adding one that already exists,
    and ``root_mismatch`` when the recomputed pack root differs from
    ``expected_new_root``. On success returns the applied ``(symbols, edges)``.
    """
    sym_map: dict[tuple[str, str], Symbol] = {}
    for s in base_symbols:
        sym_map[(s.kind, s.qualified_name)] = s

    for s in removed:
        key = (s.kind, s.qualified_name)
        if key not in sym_map:
            raise ValueError(
                f"delta_invalid: removing symbol {s.kind} {s.qualified_name} "
                "that does not exist in base"
            )
        del sym_map[key]

    for s in added:
        key = (s.kind, s.qualified_name)
        if key in sym_map:
            raise ValueError(
                f"delta_invalid: adding symbol {s.kind} {s.qualified_name} "
                "that already exists"
            )
        sym_map[key] = s

    result_symbols = list(sym_map.values())

    edge_map: dict[tuple[str, str, str], Edge] = {}
    for e in base_edges:
        edge_map[(e.source, e.target, e.edge_type)] = e

    for e in removed_edges:
        key = (e.source, e.target, e.edge_type)
        if key not in edge_map:
            raise ValueError(
                f"delta_invalid: removing edge {e.source} -> {e.target} "
                f"{e.edge_type} that does not exist"
            )
        del edge_map[key]

    for e in added_edges:
        key = (e.source, e.target, e.edge_type)
        if key in edge_map:
            raise ValueError(
                f"delta_invalid: adding edge {e.source} -> {e.target} "
                f"{e.edge_type} that already exists"
            )
        edge_map[key] = e

    result_edges = list(edge_map.values())

    computed_root = pack_root(result_symbols, result_edges)
    if computed_root != expected_new_root:
        raise ValueError(
            f"root_mismatch: computed {computed_root}, expected {expected_new_root}"
        )

    return result_symbols, result_edges
