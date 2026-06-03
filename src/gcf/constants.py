"""Kind abbreviation mappings for GCF encoding/decoding."""

# Maps full kind names to short GCF abbreviations.
KIND_ABBREV: dict[str, str] = {
    "function": "fn",
    "type": "type",
    "method": "method",
    "interface": "iface",
    "var": "var",
    "const": "const",
    "resource": "resource",
    "table": "table",
    "class": "class",
    "selector": "selector",
    "field": "field",
    "route_handler": "route",
    "external": "ext",
    "file": "file",
    "package": "pkg",
    "service": "svc",
}

# Maps short GCF abbreviations to full kind names.
KIND_EXPAND: dict[str, str] = {v: k for k, v in KIND_ABBREV.items()}
