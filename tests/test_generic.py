"""Tests for GCF generic encoding."""

from gcf import encode_generic


def test_encode_flat_tabular_list():
    """Flat tabular list of dicts produces header with fields and pipe-separated rows."""
    data = {
        "employees": [
            {"name": "Alice", "role": "engineer", "level": 5},
            {"name": "Bob", "role": "designer", "level": 3},
            {"name": "Carol", "role": "manager", "level": 7},
        ],
    }
    output = encode_generic(data)

    assert "## employees [3]{name,role,level}" in output
    assert "Alice|engineer|5" in output
    assert "Bob|designer|3" in output
    assert "Carol|manager|7" in output
    # Pure flat rows should not have @id prefix.
    lines = output.strip().splitlines()
    row_lines = [l for l in lines if "|" in l]
    for line in row_lines:
        assert not line.strip().startswith("@")


def test_encode_nested_dict():
    """Nested dicts produce ## section headers and indented key=value pairs."""
    data = {
        "server": {
            "host": "localhost",
            "port": 8080,
        },
        "debug": True,
    }
    output = encode_generic(data)

    assert "## server" in output
    assert "  host=localhost" in output
    assert "  port=8080" in output
    assert "debug=true" in output


def test_encode_mixed_data():
    """Mixed data with tabular rows containing nested fields uses @id prefix."""
    data = {
        "projects": [
            {
                "name": "Alpha",
                "status": "active",
                "config": {"env": "prod", "region": "us-east"},
            },
            {
                "name": "Beta",
                "status": "draft",
                "config": {"env": "staging", "region": "eu-west"},
            },
        ],
    }
    output = encode_generic(data)

    # Header lists only primitive fields.
    assert "## projects [2]{name,status}" in output
    # Rows with nested data get @id prefix.
    assert "@0 Alpha|active" in output
    assert "@1 Beta|draft" in output
    # Nested config values are indented.
    assert "## config" in output
    assert "env=" in output
    assert "region=" in output


def test_encode_none_value():
    """None is encoded as a dash."""
    data = {"value": None}
    output = encode_generic(data)
    assert "value=-" in output


def test_encode_none_in_tabular():
    """None values in tabular rows render as dashes."""
    data = {
        "items": [
            {"a": 1, "b": None},
            {"a": 2, "b": "hello"},
        ],
    }
    output = encode_generic(data)
    assert "1|-" in output
    assert "2|hello" in output


def test_encode_pipe_separators_in_tabular():
    """Tabular rows use pipe separators between fields."""
    data = {
        "rows": [
            {"x": 10, "y": 20, "z": 30},
            {"x": 40, "y": 50, "z": 60},
        ],
    }
    output = encode_generic(data)
    assert "10|20|30" in output
    assert "40|50|60" in output


def test_encode_no_repeated_field_names_in_rows():
    """Field names appear only in the header, not repeated in each row."""
    data = {
        "people": [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ],
    }
    output = encode_generic(data)

    # Field names appear exactly once (in the header).
    lines = output.strip().splitlines()
    header_lines = [l for l in lines if l.strip().startswith("## people")]
    assert len(header_lines) == 1
    assert "name" in header_lines[0]
    assert "age" in header_lines[0]

    # Data rows do not contain field names.
    data_lines = [l for l in lines if not l.strip().startswith("##")]
    for line in data_lines:
        assert "name=" not in line
        assert "age=" not in line


def test_encode_boolean_formatting():
    """Booleans are lowercased (true/false)."""
    data = {"enabled": True, "verbose": False}
    output = encode_generic(data)
    assert "enabled=true" in output
    assert "verbose=false" in output


def test_encode_empty_list():
    """Empty list produces a header with count zero."""
    data = {"items": []}
    output = encode_generic(data)
    assert "## items [0]" in output


def test_encode_non_uniform_list():
    """Non-uniform list items get @N indices without tabular headers."""
    data = {
        "things": [
            {"a": 1},
            {"completely": "different", "keys": True},
        ],
    }
    output = encode_generic(data)
    assert "## things [2]" in output
    assert "@0" in output
    assert "@1" in output


def test_encode_primitive_value():
    """A bare primitive is encoded directly."""
    assert encode_generic(42) == "42\n"
    assert encode_generic("hello") == "hello\n"


def test_encode_string_with_pipe():
    """Strings containing pipe characters are quoted."""
    data = {"val": "a|b"}
    output = encode_generic(data)
    assert 'val="a|b"' in output
