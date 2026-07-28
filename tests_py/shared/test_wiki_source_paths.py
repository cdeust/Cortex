"""Tests for mcp_server.shared.wiki_source_paths — path canonicalisation."""

from mcp_server.shared.wiki_source_paths import (
    extract_document_paths,
    normalize_source_path,
)


class TestNormalizeSourcePath:
    """The post-condition: forward slashes, no leading './' or '/', or None."""

    def test_leaves_an_already_canonical_path_alone(self):
        assert normalize_source_path("docs/readme.md") == "docs/readme.md"

    def test_strips_a_leading_dot_slash(self):
        assert normalize_source_path("./docs/readme.md") == "docs/readme.md"

    def test_strips_a_leading_slash(self):
        assert normalize_source_path("/docs/readme.md") == "docs/readme.md"

    def test_converts_backslashes(self):
        assert normalize_source_path("docs\\readme.md") == "docs/readme.md"

    def test_returns_none_for_blank(self):
        assert normalize_source_path("   ") is None
        assert normalize_source_path("") is None

    def test_returns_none_when_only_separators(self):
        assert normalize_source_path("///") is None
        assert normalize_source_path(".//") is None


class TestNormalizeSourcePathReachesAFixedPoint:
    """Regression: a prefix exposed by stripping another must also go.

    The original implementation stripped every leading './' in a loop and
    THEN applied lstrip('/') exactly once. Removing the slashes can expose a
    fresh './' that the loop has already walked past, so these inputs came
    back still carrying the prefix the function exists to remove. Each case
    below fails on the pre-fix implementation.
    """

    def test_dot_slash_exposed_by_stripping_slashes(self):
        assert normalize_source_path(".//./x") == "x"

    def test_slash_dot_slash(self):
        assert normalize_source_path("/./z") == "z"

    def test_repeated_alternation(self):
        assert normalize_source_path(".//.//./y") == "y"

    def test_after_backslash_conversion(self):
        assert normalize_source_path("\\\\.//./w") == "w"

    def test_result_is_idempotent(self):
        """What makes the result usable as a dedup key at all."""
        for raw in (".//./x", "/./z", ".//.//./y", "./docs/a.md", "/a/b"):
            once = normalize_source_path(raw)
            assert once is not None
            assert normalize_source_path(once) == once, raw

    def test_parent_traversal_is_left_intact(self):
        """Not in this function's contract — it canonicalises, it does not resolve.

        Pinned so a future change to the loop above does not silently start
        eating '..' segments, which would change what callers receive.
        """
        assert normalize_source_path("./../etc/passwd") == "../etc/passwd"


class TestExtractDocumentPathsDedupesAcrossSpellings:
    """The user-visible consequence of the bug above."""

    def test_two_spellings_of_one_document_collapse_to_one(self):
        paths = extract_document_paths({"documents": ["docs/a.md", ".//./docs/a.md"]})
        assert paths == ["docs/a.md"]
