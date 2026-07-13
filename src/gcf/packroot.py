"""GCF graph-profile pack root (gcf-pack-root-v1, SPEC Section 10.2).

Computes the canonical pack root hash for a graph snapshot (symbols + edges).
Mirrors the gcf-go reference implementation (packroot.go); the shared conformance
fixtures (graph-pack-root/) hold both to identical bytes and hashes.
"""

from __future__ import annotations

import hashlib

from .constants import KIND_ABBREV
from .scalar import format_number
from .types import Edge, Symbol


def pack_root(symbols: list[Symbol], edges: list[Edge]) -> str:
    """Canonical pack root for a graph snapshot (gcf-pack-root-v1, graph profile, 10.2).

    Symbol and edge records are sorted independently by unsigned UTF-8 byte order,
    then concatenated (all symbols, then all edges) and hashed with SHA-256. Two
    implementations given the same logical graph MUST produce the same result.
    """
    # Build canonical symbol records.
    sym_records: list[str] = []
    for s in symbols:
        kind = KIND_ABBREV.get(s.kind, s.kind)
        score = format_number(float(s.score))
        sym_records.append(
            f"S\t{kind}\t{s.qualified_name}\t{score}\t{s.provenance}\t{s.distance}\n"
        )

    # Map qualified_name -> kind abbreviation for edge endpoint resolution.
    sym_kind_map: dict[str, str] = {}
    for s in symbols:
        sym_kind_map[s.qualified_name] = KIND_ABBREV.get(s.kind, s.kind)

    # Build canonical edge records.
    edge_records: list[str] = []
    for e in edges:
        src_kind = sym_kind_map.get(e.source, "")
        tgt_kind = sym_kind_map.get(e.target, "")
        edge_records.append(
            f"E\t{src_kind}\t{e.source}\t{tgt_kind}\t{e.target}\t{e.edge_type}\n"
        )

    # Sort independently by unsigned UTF-8 byte order.
    sym_records.sort(key=lambda r: r.encode("utf-8"))
    edge_records.sort(key=lambda r: r.encode("utf-8"))

    canonical = "".join(sym_records) + "".join(edge_records)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "sha256:" + digest
