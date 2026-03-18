"""Tests for mcp_server.shared.yaml_parser — YAML frontmatter parsing."""

from mcp_server.shared.yaml_parser import parse_yaml_frontmatter


class TestParseYAMLFrontmatter:
    def test_parses_valid_frontmatter(self):
        content = "---\nname: test\ntype: user\n---\nBody text here"
        result = parse_yaml_frontmatter(content)
        assert result.meta == {"name": "test", "type": "user"}
        assert result.body == "Body text here"

    def test_returns_body_only_when_no_frontmatter(self):
        content = "No frontmatter here, just body text."
        result = parse_yaml_frontmatter(content)
        assert result.meta == {}
        assert result.body == "No frontmatter here, just body text."

    def test_returns_empty_for_none(self):
        result = parse_yaml_frontmatter(None)
        assert result.meta == {}
        assert result.body == ""

    def test_returns_empty_for_empty_string(self):
        result = parse_yaml_frontmatter("")
        assert result.meta == {}
        assert result.body == ""

    def test_handles_nested_colons_in_values(self):
        content = "---\nurl: http://example.com:8080/path\ntitle: My Title\n---\nBody"
        result = parse_yaml_frontmatter(content)
        assert result.meta["url"] == "http://example.com:8080/path"
        assert result.meta["title"] == "My Title"
        assert result.body == "Body"

    def test_lowercases_meta_keys(self):
        content = "---\nName: test\nType: user\n---\nBody"
        result = parse_yaml_frontmatter(content)
        assert "name" in result.meta
        assert "type" in result.meta
        assert "Name" not in result.meta

    def test_trims_whitespace_from_values(self):
        content = "---\nname:   spaced value   \n---\nBody"
        result = parse_yaml_frontmatter(content)
        assert result.meta["name"] == "spaced value"

    def test_trims_body_text(self):
        content = "---\nname: test\n---\n\n  Body with whitespace  \n\n"
        result = parse_yaml_frontmatter(content)
        assert result.body == "Body with whitespace"

    def test_handles_multiple_key_value_pairs(self):
        content = "---\na: 1\nb: 2\nc: 3\nd: 4\n---\nBody"
        result = parse_yaml_frontmatter(content)
        assert len(result.meta) == 4
        assert result.meta["a"] == "1"
        assert result.meta["d"] == "4"
