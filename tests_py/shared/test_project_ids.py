"""Tests for mcp_server.shared.project_ids — path/ID conversion."""

from mcp_server.shared.project_ids import (
    cwd_to_project_id,
    domain_id_from_label,
    project_id_to_label,
)


class TestCwdToProjectId:
    def test_converts_normal_path(self):
        assert cwd_to_project_id("/Users/dev/jarvis") == "-Users-dev-jarvis"

    def test_replaces_all_slashes(self):
        assert (
            cwd_to_project_id("/Users/dev/Developments/my-project")
            == "-Users-dev-Developments-my-project"
        )

    def test_returns_none_for_none(self):
        assert cwd_to_project_id(None) is None

    def test_returns_none_for_empty_string(self):
        assert cwd_to_project_id("") is None


class TestProjectIdToLabel:
    def test_strips_users_prefix(self):
        assert project_id_to_label("-Users-dev-Developments-jarvis") == "jarvis"

    def test_strips_documents_prefix(self):
        assert project_id_to_label("-Users-dev-Documents-myproject") == "myproject"

    def test_returns_unknown_for_none(self):
        assert project_id_to_label(None) == "Unknown"

    def test_returns_unknown_for_empty_string(self):
        assert project_id_to_label("") == "Unknown"

    def test_replaces_dashes_with_spaces(self):
        assert project_id_to_label("-Users-dev-Developments-my-project") == "my project"


class TestDomainIdFromLabel:
    def test_lowercases_label(self):
        assert domain_id_from_label("MyProject") == "myproject"

    def test_replaces_non_alphanumeric_with_dashes(self):
        assert domain_id_from_label("My Project Name") == "my-project-name"

    def test_strips_leading_and_trailing_dashes(self):
        assert domain_id_from_label("  My Project  ") == "my-project"

    def test_returns_empty_for_empty_string(self):
        assert domain_id_from_label("") == ""

    def test_returns_empty_for_none(self):
        assert domain_id_from_label(None) == ""

    def test_handles_special_characters(self):
        assert domain_id_from_label("project@v2.0!") == "project-v2-0"
