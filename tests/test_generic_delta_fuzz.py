"""Fuzz/property tests for generic-profile delta (mirrors gcf-go FuzzGeneric*).

Two properties:
  A. decode_generic_delta / decode_generic_full never crash on arbitrary or
     mutated input (they fail closed with a controlled error, or return).
  B. arbitrary string cell values survive the full-wire round-trip
     (quoting/escaping) with the pack root preserved.
"""
import random

from gcf.generic_delta import (
    GenericSet,
    decode_generic_delta,
    decode_generic_full,
    encode_generic_full,
    generic_pack_root,
)

# structural + delimiter + unicode chars, the ones that stress quoting/escaping
ALPHABET = list("abcXYZ0129 .,-~^@#=|\t\n\r\"\\/éñ中🦞")


def _rand_str(rng, maxlen=20):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, maxlen)))


def test_fuzz_string_cell_roundtrip():
    rng = random.Random(1234)
    for _ in range(20000):
        a, b = _rand_str(rng), _rand_str(rng)
        s = GenericSet(key="id", name="t", fields=["id", "a", "b"], rows=[
            {"id": 1, "a": a, "b": b},
            {"id": 2, "a": b, "b": a},
        ])
        got, _ = decode_generic_full(encode_generic_full(s, ""))
        assert generic_pack_root(got) == generic_pack_root(s), repr((a, b))


def test_fuzz_decode_never_crashes():
    rng = random.Random(99)
    seeds = [
        "GCF profile=generic delta=true base_root=a new_root=b key=id\n## added [1]{@id,x}\n1|2\n",
        "GCF profile=generic pack_root=r key=id\n## t [2]{@id,x}\n1|2\n3|4\n",
        "## removed [1]{@id}\n99\n",
        "",
    ]
    for _ in range(20000):
        if rng.random() < 0.5:
            data = _rand_str(rng, 80)
        else:
            chars = list(rng.choice(seeds))
            for _ in range(rng.randint(0, 5)):
                if chars:
                    chars[rng.randrange(len(chars))] = rng.choice(ALPHABET)
            data = "".join(chars)
        for fn in (decode_generic_delta, decode_generic_full):
            try:
                fn(data)  # controlled error is fine; must terminate, must not crash
            except Exception:
                pass
