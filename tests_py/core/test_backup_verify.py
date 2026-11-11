"""A tree's scan is compared with a backup manifest (issue #731, slice 4)."""

from __future__ import annotations

import pytest

from mcp_server.core.backup_manifest import build_manifest, resources_for
from mcp_server.core.backup_verify import manifest_differences

_A, _B = "a" * 64, "b" * 64
_WIKI = "methodology/wiki"
_LOG = "methodology/session-log.json"


def _manifest(**scanned):
    names = {spec.name: None for spec in resources_for("postgresql")}
    return build_manifest("postgresql", {**names, **scanned}, "2026-11-11T00:00:00")


def test_two_scans_of_the_same_files_do_not_differ_whatever_their_instant():
    expected = _manifest(wiki=[(f"{_WIKI}/1.md", _A, 4)], session_log=[(_LOG, _B, 2)])
    actual = {**expected, "created_at": "2027-01-01T00:00:00"}
    assert manifest_differences(expected, actual) == []


def test_every_missing_extra_and_changed_file_is_named_in_path_order():
    expected = _manifest(
        wiki=[
            (f"{_WIKI}/changed.md", _A, 4),
            (f"{_WIKI}/gone.md", _A, 4),
            (f"{_WIKI}/same.md", _A, 4),
        ]
    )
    actual = _manifest(
        wiki=[
            (f"{_WIKI}/added.md", _A, 4),
            (f"{_WIKI}/changed.md", _B, 4),
            (f"{_WIKI}/same.md", _A, 4),
        ]
    )
    assert manifest_differences(expected, actual) == [
        f"{_WIKI}/added.md: not in the manifest",
        f"{_WIKI}/changed.md: content differs from the manifest",
        f"{_WIKI}/gone.md: absent",
    ]


def test_a_file_of_another_size_differs_even_with_the_same_digest():
    expected = _manifest(session_log=[(_LOG, _A, 2)])
    actual = _manifest(session_log=[(_LOG, _A, 3)])
    assert manifest_differences(expected, actual) == [
        f"{_LOG}: content differs from the manifest"
    ]


def test_an_empty_directory_the_tree_lacks_is_absent():
    assert manifest_differences(_manifest(wiki=[]), _manifest()) == [f"{_WIKI}: absent"]


def test_a_resource_the_manifest_calls_absent_is_extra_in_the_tree():
    actual = _manifest(wiki=[(f"{_WIKI}/1.md", _A, 4)])
    assert manifest_differences(_manifest(), actual) == [
        f"{_WIKI}: not in the manifest"
    ]


def test_differences_follow_the_resource_table_order():
    expected = _manifest(wiki=[], session_log=[(_LOG, _A, 2)])
    assert manifest_differences(expected, _manifest()) == [
        f"{_WIKI}: absent",
        f"{_LOG}: absent",
    ]


def test_manifests_of_two_backend_tables_are_not_compared():
    store = [("methodology/memory.db", _A, 1)]
    names = {spec.name: None for spec in resources_for("sqlite")}
    sqlite = build_manifest("sqlite", {**names, "sqlite_store": store}, "2026-11-11")
    with pytest.raises(ValueError, match="zip"):
        manifest_differences(sqlite, _manifest())
    with pytest.raises(ValueError, match="zip"):
        manifest_differences(_manifest(), sqlite)
