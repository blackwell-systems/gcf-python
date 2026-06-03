"""Data types for GCF payloads."""

from dataclasses import dataclass, field


@dataclass
class Components:
    """Score breakdown for a symbol."""

    blast_radius: float = 0.0
    confidence: float = 0.0
    recency: float = 0.0
    distance: float = 0.0


@dataclass
class Symbol:
    """A node in a GCF payload."""

    qualified_name: str = ""
    kind: str = ""
    score: float = 0.0
    provenance: str = ""
    distance: int = 0
    signature: str = ""
    components: Components = field(default_factory=Components)


@dataclass
class Edge:
    """A directed relationship in a GCF payload."""

    source: str = ""
    target: str = ""
    edge_type: str = ""
    status: str = ""


@dataclass
class Payload:
    """Input/output structure for GCF encoding/decoding."""

    tool: str = ""
    tokens_used: int = 0
    token_budget: int = 0
    pack_root: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


@dataclass
class DeltaPayload:
    """Diff between a prior context pack and the current result."""

    tool: str = ""
    base_root: str = ""
    new_root: str = ""
    removed: list[Symbol] = field(default_factory=list)
    added: list[Symbol] = field(default_factory=list)
    removed_edges: list[Edge] = field(default_factory=list)
    added_edges: list[Edge] = field(default_factory=list)
    delta_tokens: int = 0
    full_tokens: int = 0
