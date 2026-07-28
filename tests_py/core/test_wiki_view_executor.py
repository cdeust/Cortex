"""Tests for mcp_server.core.wiki_view_executor (#196).

compile_view is pure logic (parse YAML-ish -> whitelist-validated ->
parameterised SQL) with zero prior test coverage. Adversarial-payload
tests are mandatory here (coding-standards.md §13.1 D1: this module
builds SQL from data — every value must go through bind params, every
column name through a hardcoded whitelist).
"""

from __future__ import annotations

from mcp_server.core.wiki_view_executor import (
    CompiledView,
    _coerce_scalar,
    _compile_where,
    _is_indented,
    _parse_kv_line,
    _parse_yamlish,
    compile_view,
)


class TestParseKvLine:
    def test_simple_key_value(self):
        assert _parse_kv_line("table: pages") == ("table", "pages")

    def test_no_colon_returns_none(self):
        assert _parse_kv_line("no colon here") is None

    def test_line_exceeding_max_length_returns_none(self):
        assert _parse_kv_line("k: " + ("x" * 2000)) is None

    def test_invalid_key_returns_none(self):
        assert _parse_kv_line("123bad: value") is None

    def test_key_with_underscore_valid(self):
        assert _parse_kv_line("lifecycle_state: active") == (
            "lifecycle_state",
            "active",
        )

    def test_empty_value(self):
        assert _parse_kv_line("where:") == ("where", "")

    def test_strips_whitespace(self):
        assert _parse_kv_line("  table  :  pages  ") == ("table", "pages")


class TestCoerceScalar:
    def test_empty_string_is_none(self):
        assert _coerce_scalar("") is None

    def test_true_false(self):
        assert _coerce_scalar("true") is True
        assert _coerce_scalar("false") is False
        assert _coerce_scalar("TRUE") is True

    def test_null_variants(self):
        assert _coerce_scalar("null") is None
        assert _coerce_scalar("none") is None
        assert _coerce_scalar("~") is None

    def test_inline_list(self):
        assert _coerce_scalar("[active, evergreen]") == ["active", "evergreen"]

    def test_empty_inline_list(self):
        assert _coerce_scalar("[]") == []

    def test_quoted_string(self):
        assert _coerce_scalar("'hello'") == "hello"
        assert _coerce_scalar('"hello"') == "hello"

    def test_integer(self):
        assert _coerce_scalar("42") == 42
        assert isinstance(_coerce_scalar("42"), int)

    def test_float(self):
        assert _coerce_scalar("0.5") == 0.5

    def test_plain_string_passthrough(self):
        assert _coerce_scalar("budding") == "budding"


class TestIsIndented:
    def test_space_prefix(self):
        assert _is_indented("  key: value") is True

    def test_tab_prefix(self):
        assert _is_indented("\tkey: value") is True

    def test_no_indent(self):
        assert _is_indented("key: value") is False

    def test_empty_line(self):
        assert _is_indented("") is False


class TestParseYamlish:
    def test_top_level_scalar(self):
        result = _parse_yamlish("table: pages\nlimit: 20")
        assert result == {"table": "pages", "limit": 20}

    def test_nested_dict(self):
        text = "where:\n  kind: spec\n  status: budding"
        result = _parse_yamlish(text)
        assert result == {"where": {"kind": "spec", "status": "budding"}}

    def test_blank_lines_and_comments_skipped(self):
        text = "table: pages\n\n# a comment\nlimit: 10"
        result = _parse_yamlish(text)
        assert result == {"table": "pages", "limit": 10}

    def test_invalid_line_skipped(self):
        text = "table: pages\nnot valid at all\nlimit: 10"
        result = _parse_yamlish(text)
        assert result == {"table": "pages", "limit": 10}

    def test_list_value(self):
        text = "where:\n  lifecycle_state: [active, evergreen]"
        result = _parse_yamlish(text)
        assert result["where"]["lifecycle_state"] == ["active", "evergreen"]

    def test_empty_text_returns_empty_dict(self):
        assert _parse_yamlish("") == {}

    def test_orphaned_indented_line_at_top_skipped(self):
        # An indented line with nothing preceding it (no open nested
        # block) hits the top-level `_is_indented` continue branch.
        text = "  orphan: value\ntable: pages"
        result = _parse_yamlish(text)
        assert result == {"table": "pages"}

    def test_blank_line_inside_nested_block_skipped(self):
        text = "where:\n  kind: spec\n\n  status: budding\ntable: pages"
        result = _parse_yamlish(text)
        assert result["where"] == {"kind": "spec", "status": "budding"}
        assert result["table"] == "pages"


class TestCompileWhere:
    def test_plain_equality(self):
        frags, params, errors = _compile_where({"kind": "spec"}, {"kind"})
        assert frags == ["kind = %s"]
        assert params == ["spec"]
        assert errors == []

    def test_unknown_column_rejected(self):
        frags, params, errors = _compile_where({"evil": "x"}, {"kind"})
        assert frags == []
        assert "unknown column: 'evil'" in errors[0]

    def test_min_suffix_operator(self):
        frags, params, errors = _compile_where({"heat_min": 0.5}, {"heat"})
        assert frags == ["heat >= %s"]
        assert params == [0.5]

    def test_max_suffix_operator(self):
        frags, params, errors = _compile_where({"heat_max": 0.9}, {"heat"})
        assert frags == ["heat <= %s"]

    def test_after_suffix_operator(self):
        frags, params, errors = _compile_where(
            {"created_at_after": "2024-01-01"}, {"created_at"}
        )
        assert frags == ["created_at > %s"]

    def test_before_suffix_operator(self):
        frags, params, errors = _compile_where(
            {"created_at_before": "2024-01-01"}, {"created_at"}
        )
        assert frags == ["created_at < %s"]

    def test_list_value_produces_in_clause(self):
        frags, params, errors = _compile_where(
            {"lifecycle_state": ["active", "evergreen"]}, {"lifecycle_state"}
        )
        assert frags == ["lifecycle_state IN (%s, %s)"]
        assert params == ["active", "evergreen"]

    def test_list_value_with_non_equality_operator_rejected(self):
        frags, params, errors = _compile_where({"heat_min": [1, 2]}, {"heat"})
        assert frags == []
        assert "list value not supported" in errors[0]

    def test_none_value_produces_is_null(self):
        frags, params, errors = _compile_where({"archived_at": None}, {"archived_at"})
        assert frags == ["archived_at IS NULL"]
        assert params == []


class TestCompileView:
    def test_default_table_is_pages(self):
        result = compile_view("limit: 10")
        assert result.table == "pages"
        assert "wiki.pages" in result.sql

    def test_unknown_table_rejected(self):
        result = compile_view("table: users")
        assert not result.ok
        assert "unknown table" in result.errors[0]
        assert result.sql == ""

    def test_valid_full_query(self):
        text = (
            "table: pages\n"
            "where:\n"
            "  kind: spec\n"
            "  heat_min: 0.5\n"
            "order_by: heat\n"
            "direction: desc\n"
            "limit: 20\n"
        )
        result = compile_view(text)
        assert result.ok
        assert "SELECT * FROM wiki.pages" in result.sql
        assert "WHERE kind = %s AND heat >= %s" in result.sql
        assert "ORDER BY heat DESC NULLS LAST" in result.sql
        assert result.params == ["spec", 0.5, 20]

    def test_select_projection_whitelisted(self):
        text = "table: pages\nselect: [id, title, evil_column]"
        result = compile_view(text)
        assert "SELECT id, title FROM" in result.sql

    def test_select_all_columns_invalid_falls_back_to_id(self):
        text = "table: pages\nselect: [not_a_col]"
        result = compile_view(text)
        assert not result.ok
        assert "SELECT id FROM" in result.sql

    def test_unknown_order_by_column_rejected(self):
        result = compile_view("table: pages\norder_by: evil_col")
        assert not result.ok
        assert "unknown order_by column" in result.errors[0]

    def test_invalid_direction_defaults_to_desc(self):
        result = compile_view("table: pages\norder_by: heat\ndirection: sideways")
        assert not result.ok
        assert "direction must be" in result.errors[0]
        assert "DESC" in result.sql

    def test_limit_clamped_to_max(self):
        result = compile_view("table: pages\nlimit: 999999")
        assert result.params[-1] == 500

    def test_limit_clamped_to_minimum_one(self):
        result = compile_view("table: pages\nlimit: -5")
        assert result.params[-1] == 1

    def test_non_integer_limit_rejected_and_defaults(self):
        result = compile_view("table: pages\nlimit: not_a_number")
        assert not result.ok
        assert "limit must be an integer" in result.errors[0]
        assert result.params[-1] == 50

    def test_no_where_clause_when_empty(self):
        result = compile_view("table: pages")
        assert "WHERE" not in result.sql

    def test_ok_property_true_without_errors(self):
        result = compile_view("table: pages")
        assert result.ok is True

    def test_ok_property_false_with_errors(self):
        result = compile_view("table: users")
        assert result.ok is False


class TestCompileViewAdversarial:
    """coding-standards.md §13.1 D1: injection-class defects must be
    excluded via whitelisting/bind params, with adversarial-payload
    tests proving it — this module builds SQL from parsed user data."""

    def test_sql_injection_in_where_value_is_bound_not_concatenated(self):
        text = 'table: pages\nwhere:\n  kind: "spec\'; DROP TABLE pages; --"'
        result = compile_view(text)
        assert "DROP TABLE" not in result.sql
        assert result.params[0] == "spec'; DROP TABLE pages; --"

    def test_sql_injection_in_table_name_rejected(self):
        result = compile_view("table: pages; DROP TABLE pages;--")
        assert not result.ok
        assert "DROP TABLE" not in result.sql

    def test_sql_injection_in_column_name_rejected(self):
        text = 'table: pages\nwhere:\n  "id; DROP TABLE pages;--": 1'
        result = compile_view(text)
        # The malicious "column" fails the whitelist check either via
        # unknown-column rejection or the key regex; either way it
        # never reaches the emitted SQL.
        assert "DROP TABLE" not in result.sql

    def test_sql_injection_in_order_by_rejected(self):
        result = compile_view("table: pages\norder_by: heat; DROP TABLE pages;--")
        assert not result.ok
        assert "DROP TABLE" not in result.sql

    def test_oversized_line_does_not_crash_parser(self):
        text = "table: pages\nwhere:\n  kind: " + ("x" * 5000)
        result = compile_view(text)
        assert isinstance(result, CompiledView)

    def test_deeply_nested_garbage_does_not_crash(self):
        text = "table: pages\n" + ("  " * 50) + "garbage: value"
        result = compile_view(text)
        assert isinstance(result, CompiledView)

    def test_empty_input_produces_valid_default_query(self):
        result = compile_view("")
        assert result.ok
        assert "wiki.pages" in result.sql
