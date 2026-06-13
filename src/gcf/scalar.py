"""Common scalar grammar for GCF v2.0."""

from __future__ import annotations

import math
import re
from typing import Any

_JSON_NUMBER_RE = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_NUMERIC_LIKE_RE = re.compile(r"^[+-]\.?\d|^\.\d|^0\d")
_BARE_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class _Missing:
    """Sentinel for absent fields in tabular rows."""
    __slots__ = ()

class _Attachment:
    """Sentinel for nested value placeholders in tabular rows."""
    __slots__ = ()

MISSING = _Missing()
ATTACHMENT = _Attachment()


def needs_quote(s: str) -> bool:
    if s == "":
        return True
    if s in ("-", "~", "^", "true", "false"):
        return True
    if _JSON_NUMBER_RE.match(s):
        return True
    if _NUMERIC_LIKE_RE.match(s):
        return True
    if s[0] == " " or s[-1] == " ":
        return True
    if s[0] in ("#", "@", "."):
        return True
    for c in s:
        o = ord(c)
        if c in ('"', "\\", "|") or o < 0x20 or c in ("\n", "\r"):
            return True
        # C1 control characters
        if 0x80 <= o <= 0x9F:
            return True
        # Unicode whitespace beyond ASCII
        if o > 0x7F and o in (0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF) or (0x2000 <= o <= 0x200A):
            return True
    return False


def quote_string(s: str) -> str:
    out = ['"']
    for c in s:
        o = ord(c)
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\b":
            out.append("\\b")
        elif c == "\f":
            out.append("\\f")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif o < 0x20:
            out.append(f"\\u{o:04x}")
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


def format_scalar(v: Any, delimiter: str = "") -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return format_number(v)
    s = str(v)
    if needs_quote(s) or (delimiter and delimiter in s):
        return quote_string(s)
    return s


def format_number(f: float) -> str:
    if f != f:  # NaN
        return "0"
    if math.isinf(f):
        return "0"
    if f == 0.0:
        return "-0" if math.copysign(1.0, f) < 0 else "0"
    a = abs(f)
    if 1e-6 <= a < 1e21:
        # Use repr for shortest round-trippable form.
        s = repr(f)
        # If repr chose scientific notation, convert to plain decimal.
        if "e" in s or "E" in s:
            # Format with enough precision, then strip trailing zeros.
            s = f"{f:.20f}".rstrip("0").rstrip(".")
        # Strip trailing .0 for integer-valued floats.
        if s.endswith(".0") and f == int(f):
            s = s[:-2]
        return s
    # Exponent notation. Use repr for shortest round-trippable form.
    s = repr(f)
    # repr may already be in scientific notation. If not, convert.
    if "e" not in s and "E" not in s:
        s = f"{f:.17e}"
    # Normalize: lowercase e, strip trailing zeros from mantissa, explicit sign, no leading zeros in exponent.
    s = s.lower()
    parts = s.split("e")
    mantissa = parts[0].rstrip("0").rstrip(".")
    exp = parts[1]
    sign = "+" if not exp.startswith("-") else "-"
    digits = exp.lstrip("+-").lstrip("0") or "0"
    return f"{mantissa}e{sign}{digits}"


def is_bare_key(s: str) -> bool:
    return bool(_BARE_KEY_RE.match(s))


def format_key(s: str) -> str:
    return s if is_bare_key(s) else quote_string(s)


def parse_scalar(s: str, tabular_context: bool = False) -> Any:
    if s == "":
        return ""
    if s[0] == '"':
        return parse_quoted_string(s)
    if s == "-":
        return None
    if s == "~":
        if not tabular_context:
            raise ValueError("invalid_missing: ~ outside tabular row cell")
        return MISSING
    if s == "^":
        if not tabular_context:
            raise ValueError("invalid_attachment_marker: ^ outside tabular row cell")
        return ATTACHMENT
    if s == "true":
        return True
    if s == "false":
        return False
    if _JSON_NUMBER_RE.match(s):
        try:
            f = float(s)
            if "." not in s and "e" not in s and "E" not in s:
                if abs(f) <= 2**53:
                    return int(f)
            return f
        except ValueError:
            pass
    return s


def parse_quoted_string(s: str) -> str:
    if len(s) < 2 or s[0] != '"':
        raise ValueError("unterminated_quote")
    out: list[str] = []
    i = 1
    while i < len(s):
        if s[i] == '"':
            if i + 1 != len(s):
                raise ValueError("trailing_characters: after closing quote")
            return "".join(out)
        if s[i] == "\\":
            if i + 1 >= len(s):
                raise ValueError("unterminated_quote")
            i += 1
            c = s[i]
            if c == '"':
                out.append('"')
            elif c == "\\":
                out.append("\\")
            elif c == "/":
                out.append("/")
            elif c == "b":
                out.append("\b")
            elif c == "f":
                out.append("\f")
            elif c == "n":
                out.append("\n")
            elif c == "r":
                out.append("\r")
            elif c == "t":
                out.append("\t")
            elif c == "u":
                if i + 4 >= len(s):
                    raise ValueError("invalid_escape: incomplete unicode")
                h = s[i + 1 : i + 5]
                try:
                    code = int(h, 16)
                except ValueError:
                    raise ValueError(f"invalid_escape: invalid unicode \\u{h}")
                if 0xD800 <= code <= 0xDBFF:
                    if i + 10 >= len(s) or s[i + 5] != "\\" or s[i + 6] != "u":
                        raise ValueError("invalid_surrogate: isolated high surrogate")
                    h2 = s[i + 7 : i + 11]
                    try:
                        low = int(h2, 16)
                    except ValueError:
                        raise ValueError(f"invalid_surrogate: invalid low surrogate \\u{h2}")
                    if low < 0xDC00 or low > 0xDFFF:
                        raise ValueError(f"invalid_surrogate: expected low surrogate")
                    combined = 0x10000 + (code - 0xD800) * 0x400 + (low - 0xDC00)
                    out.append(chr(combined))
                    i += 11
                    continue
                if 0xDC00 <= code <= 0xDFFF:
                    raise ValueError("invalid_surrogate: isolated low surrogate")
                out.append(chr(code))
                i += 5
                continue
            else:
                raise ValueError(f"invalid_escape: unknown \\{c}")
            i += 1
            continue
        if ord(s[i]) < 0x20:
            raise ValueError(f"invalid_escape: unescaped control U+{ord(s[i]):04x}")
        out.append(s[i])
        i += 1
    raise ValueError("unterminated_quote")


def split_respecting_quotes(s: str, delim: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    escaped = False
    for c in s:
        if escaped:
            current.append(c)
            escaped = False
            continue
        if c == "\\" and in_quote:
            current.append(c)
            escaped = True
            continue
        if c == '"':
            in_quote = not in_quote
            current.append(c)
            continue
        if c == delim and not in_quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(c)
    parts.append("".join(current))
    return parts


def split_field_decl(s: str) -> list[str]:
    if len(s) < 2 or s[0] != "{":
        raise ValueError(f"invalid field declaration: {s}")
    close = _find_closing_brace(s)
    if close < 0:
        raise ValueError(f"invalid field declaration: {s}")
    inner = s[1:close]
    if not inner:
        return []
    raw = split_respecting_quotes(inner, ",")
    fields: list[str] = []
    seen: set[str] = set()
    for f in raw:
        f = f.strip()
        if len(f) >= 2 and f[0] == '"' and f[-1] == '"':
            name = parse_quoted_string(f)
        else:
            if not is_bare_key(f):
                raise ValueError(f"invalid field name: {f}")
            name = f
        if name in seen:
            raise ValueError(f"duplicate_field_name: {name}")
        seen.add(name)
        fields.append(name)
    return fields


def _find_closing_brace(s: str) -> int:
    in_quote = False
    escaped = False
    for i, c in enumerate(s):
        if escaped:
            escaped = False
            continue
        if c == "\\" and in_quote:
            escaped = True
            continue
        if c == '"':
            in_quote = not in_quote
            continue
        if c == "}" and not in_quote:
            return i
    return -1
