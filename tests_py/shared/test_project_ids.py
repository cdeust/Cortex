"""Tests for mcp_server.shared.project_ids — path/ID conversion."""

from mcp_server.shared.project_ids import (
    cwd_to_project_id,
    domain_id_from_label,
    normalize_project_id,
    project_id_to_label,
)


class TestCwdToProjectId:
    def test_converts_normal_path(self):
        assert cwd_to_project_id("/Users/dev/cortex") == "-Users-dev-cortex"

    def test_replaces_all_slashes(self):
        assert (
            cwd_to_project_id("/Users/dev/Developments/my-project")
            == "-Users-dev-Developments-my-project"
        )

    def test_returns_none_for_none(self):
        assert cwd_to_project_id(None) is None

    def test_returns_none_for_empty_string(self):
        assert cwd_to_project_id("") is None

    # ── Cross-platform: Windows / Git-Bash forms (issue #18) ────────────

    def test_windows_forward_slash(self):
        # PSGSupport reporter data: 'C:/Users/michael.crawford' must produce
        # the same slug as the on-disk domain c--users-michael-crawford.
        assert (
            cwd_to_project_id("C:/Users/michael.crawford")
            == "c--users-michael-crawford"
        )

    def test_windows_backslash(self):
        assert (
            cwd_to_project_id("C:\\Users\\michael.crawford")
            == "c--users-michael-crawford"
        )

    def test_gitbash_drive_translation(self):
        # Git-Bash represents 'C:/...' as '/c/...'. Same logical path → same slug.
        assert (
            cwd_to_project_id("/c/users/michael.crawford")
            == "c--users-michael-crawford"
        )

    def test_bare_drive(self):
        assert cwd_to_project_id("C:/") == "c--"
        assert cwd_to_project_id("C:\\") == "c--"

    def test_windows_lowercases_drive(self):
        # Drive letter case shouldn't matter — same path, same slug.
        assert cwd_to_project_id("c:/Users/foo") == cwd_to_project_id("C:/Users/foo")

    def test_idempotent_on_existing_posix_slug(self):
        # Round-trip: existing slugs in profiles.json must survive a re-pass.
        slug = "-Users-cdeust-Developments-Cortex"
        assert cwd_to_project_id(slug) == slug

    def test_idempotent_on_existing_windows_slug(self):
        slug = "c--users-michael-crawford"
        assert cwd_to_project_id(slug) == slug

    def test_windows_dotted_filename_segment(self):
        # Dots are non-alnum and must collapse to '-' on Windows paths,
        # matching the Claude Code on-disk convention.
        assert (
            cwd_to_project_id("C:/Users/michael.crawford/Project.Name")
            == "c--users-michael-crawford-project-name"
        )


class TestProjectIdToLabel:
    def test_strips_users_prefix(self):
        assert project_id_to_label("-Users-dev-Developments-cortex") == "cortex"

    def test_strips_documents_prefix(self):
        assert project_id_to_label("-Users-dev-Documents-myproject") == "myproject"

    def test_returns_unknown_for_none(self):
        assert project_id_to_label(None) == "Unknown"

    def test_returns_unknown_for_empty_string(self):
        assert project_id_to_label("") == "Unknown"

    def test_replaces_dashes_with_spaces(self):
        assert project_id_to_label("-Users-dev-Developments-my-project") == "my project"


class TestNormalizeProjectId:
    # ── issue #95: mbe14's live-verified repro ──────────────────────────
    def test_lowercases_windows_slug_to_match_stored_original_casing(self):
        # cwd_to_project_id derives 'c--work-myrepo' (lowercase); the
        # profile stores 'C--Work-MyRepo' (original filesystem casing).
        assert normalize_project_id("c--work-myrepo") == normalize_project_id(
            "C--Work-MyRepo"
        )

    def test_returns_none_for_none(self):
        assert normalize_project_id(None) is None

    def test_returns_none_for_empty_string(self):
        assert normalize_project_id("") is None

    def test_lowercases_input(self):
        assert normalize_project_id("C--Work-MyRepo") == "c--work-myrepo"

    def test_idempotent_on_already_lowercase(self):
        assert normalize_project_id("-users-dev-cortex") == "-users-dev-cortex"

    def test_posix_ids_differing_only_by_case_fold_equal(self):
        # source: ADR-1055  # noqa: ERA001
        assert normalize_project_id("-Users-dev-Foo") == normalize_project_id(
            "-Users-dev-foo"
        )


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
