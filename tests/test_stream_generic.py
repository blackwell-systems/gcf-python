"""Tests for the GenericStreamEncoder."""

import io

from gcf import GenericStreamEncoder


def test_tabular():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("employees", ["id", "name", "department", "salary"])
    enc.write_row([1, "Alice", "Engineering", 95000])
    enc.write_row([2, "Bob", "Sales", 72000])
    enc.write_row([3, "Carol", "Marketing", 85000])
    enc.end_array()
    enc.close()

    out = buf.getvalue()
    assert "## employees [?]{id,name,department,salary}" in out
    assert "1|Alice|Engineering|95000" in out
    assert "## _summary rows=3 sections=employees:3" in out


def test_kv_and_inline_array():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.write_kv("name", "my-service")
    enc.write_kv("version", "2.1.0")
    enc.write_inline_array("tags", ["production", "us-east-1", "critical"])
    enc.close()

    out = buf.getvalue()
    assert "name=my-service" in out
    assert "tags[3]: production,us-east-1,critical" in out


def test_incremental():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("data", ["id", "val"])
    assert len(buf.getvalue()) > 0, "header should be written immediately"

    header_len = len(buf.getvalue())
    enc.write_row([1, "a"])
    assert len(buf.getvalue()) > header_len, "row should be written immediately"

    enc.end_array()
    enc.close()


def test_multiple_arrays():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("users", ["id", "name"])
    enc.write_row([1, "Alice"])
    enc.write_row([2, "Bob"])
    enc.end_array()

    enc.begin_array("roles", ["name", "level"])
    enc.write_row(["admin", 10])
    enc.end_array()

    enc.close()

    out = buf.getvalue()
    assert "sections=users:2,roles:1" in out


def test_null_and_bool():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("data", ["a", "b", "c"])
    enc.write_row([None, True, False])
    enc.end_array()
    enc.close()

    out = buf.getvalue()
    assert "-|true|false" in out


def test_empty_string_and_pipe():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("data", ["a", "b"])
    enc.write_row(["", "has|pipe"])
    enc.end_array()
    enc.close()

    out = buf.getvalue()
    assert '""|"has|pipe"' in out


def test_auto_close_on_begin_array():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("first", ["a"])
    enc.write_row([1])
    enc.begin_array("second", ["b"])
    enc.write_row([2])
    enc.end_array()
    enc.close()

    out = buf.getvalue()
    assert "sections=first:1,second:1" in out


def test_write_section():
    buf = io.StringIO()
    enc = GenericStreamEncoder(buf)

    enc.begin_array("items", ["id"])
    enc.write_row([1])
    enc.write_section("metadata")
    enc.write_kv("count", 1)
    enc.close()

    out = buf.getvalue()
    assert "## metadata" in out
    assert "## _summary rows=1 sections=items:1" in out
