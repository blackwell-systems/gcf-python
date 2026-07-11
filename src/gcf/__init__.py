"""GCF (Graph Compact Format): token-optimized wire format for LLM tool responses.

84% fewer tokens than JSON. 32% fewer than TOON. 100% LLM comprehension accuracy.

Encode a payload:

    from gcf import encode, Payload, Symbol

    p = Payload(
        tool="context_for_task",
        token_budget=5000,
        tokens_used=1847,
        symbols=[Symbol(qualified_name="pkg.Func", kind="function", score=0.9, provenance="lsp_resolved")],
    )
    output = encode(p)

Decode a payload:

    from gcf import decode
    p = decode(input_text)

Session deduplication:

    from gcf import encode_with_session, Session
    sess = Session()
    out1 = encode_with_session(payload1, sess)  # full declarations
    out2 = encode_with_session(payload2, sess)  # reused symbols as bare refs

Delta encoding:

    from gcf import encode_delta, DeltaPayload
    out = encode_delta(DeltaPayload(...))

Specification: https://github.com/blackwell-systems/gcf
"""

from .constants import KIND_ABBREV, KIND_EXPAND
from .decode import DecodeError, decode
from .delta import encode_delta
from .encode import encode
from .generic import encode_generic, GenericOptions
from .session import Session, encode_with_session
from .decode_generic import decode_generic
from .stream import StreamEncoder
from .stream_generic import GenericStreamEncoder
from .types import Components, DeltaPayload, Edge, Payload, Symbol

__all__ = [
    "Components",
    "DecodeError",
    "DeltaPayload",
    "GenericStreamEncoder",
    "Edge",
    "KIND_ABBREV",
    "KIND_EXPAND",
    "Payload",
    "Session",
    "StreamEncoder",
    "Symbol",
    "decode",
    "decode_generic",
    "encode",
    "encode_delta",
    "encode_generic",
    "GenericOptions",
    "encode_with_session",
]

__version__ = "2.2.2"
