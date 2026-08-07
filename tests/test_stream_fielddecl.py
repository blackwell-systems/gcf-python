"""Property fuzz for the streaming tabular header field declaration.

GenericStreamEncoder.begin_array previously joined field names raw, so a name
containing a delimiter or quote produced an invalid or ambiguous field
declaration (row_width_mismatch / invalid field name). Field names now format
via format_key (Section 2.4), matching the buffered tabular header. A field name
containing ">" is rejected (a flattened path is not representable in a flat
streaming row, SPEC 8.3); that path is asserted separately.
"""

import io
import os
import random

from gcf import GenericStreamEncoder, decode_generic

_ALPHABET = list("abcXYZ_0123 ,|\"@#.")


def _iterations(default: int) -> int:
    override = os.getenv("GCF_FUZZ_ITERATIONS")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return default


def _gen_key(rng: random.Random) -> str:
    n = rng.randint(0, 6)
    return "".join(rng.choice(_ALPHABET) for _ in range(n))


def _gen_scalar(rng: random.Random):
    kind = rng.randint(0, 5)
    if kind == 0:
        return rng.randint(-1000, 1000)
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return None
    if kind == 3:
        return round(rng.uniform(-100, 100), 3)
    # Strings, including some that need quoting.
    n = rng.randint(0, 6)
    return "".join(rng.choice(_ALPHABET) for _ in range(n))


def test_fuzz_stream_field_names_roundtrip():
    iterations = _iterations(200000)
    rng = random.Random(0x5738)
    saw_special = False
    for i in range(iterations):
        nf = rng.randint(1, 5)
        fields: list[str] = []
        while len(fields) < nf:
            f = _gen_key(rng)
            if ">" in f:
                continue  # ">" is rejected, tested separately
            if f in fields:
                continue
            fields.append(f)
            if f == "" or any(c in f for c in ",|\""):
                saw_special = True

        nr = rng.randint(1, 6)
        buf = io.StringIO()
        enc = GenericStreamEncoder(buf)
        enc.begin_array("rows", fields)
        expected = []
        for _ in range(nr):
            row = []
            obj = {}
            for f in fields:
                v = _gen_scalar(rng)
                row.append(v)
                obj[f] = v
            enc.write_row(row)
            expected.append(obj)
        enc.end_array()
        enc.close()

        wire = buf.getvalue()
        decoded = decode_generic(wire)
        want = {"rows": expected}
        assert decoded == want, (
            f"iter {i}: round-trip mismatch\n want: {want}\n got:  {decoded}\n"
            f" fields: {fields}\n wire: {wire!r}"
        )

    # Liveness: the generator must have produced at least one field name that
    # requires quoting, or the fuzz proves nothing about the fix.
    assert saw_special, "generator never produced a field name needing quoting (empty / , | \")"


def test_stream_field_name_gt_rejected():
    """A streaming value field name containing ">" is rejected (SPEC 8.3),
    surfaced at close()."""
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)
    enc.begin_array("rows", ["id", "a>b"])
    enc.write_row([1, 2])
    enc.end_array()
    raised = False
    try:
        enc.close()
    except ValueError:
        raised = True
    assert raised, f"expected an error for a '>' field name, got none\n wire: {buf.getvalue()!r}"
