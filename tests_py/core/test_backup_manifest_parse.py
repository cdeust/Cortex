"""Canonical text and parse of the backup manifest (issue #731, slice 2)."""

from __future__ import annotations

import json

import pytest

from mcp_server.core import backup_manifest as bm

DIGEST = "a" * 64
OTHER = "0123456789abcdef" * 4


def _scan(backend: str, **present) -> dict:
    scanned = {spec.name: None for spec in bm.resources_for(backend)}
    scanned.update(present)
    return scanned


def _sqlite_scan(**present) -> dict:
    return _scan(
        "sqlite", sqlite_store=[("methodology/memory.db", DIGEST, 10)], **present
    )


# --- canonical text and parse ----------------------------------------------------


def test_to_json_is_canonical_and_parses_back_unchanged():
    manifest = bm.build_manifest("sqlite", _sqlite_scan(), "t")
    text = bm.to_json(manifest)
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text == json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    assert bm.to_json({"b": "é", "a": 1}) == '{\n  "a": 1,\n  "b": "\\u00e9"\n}\n'
    assert bm.parse_manifest(text) == manifest


def _text(**override) -> str:
    manifest = bm.build_manifest("sqlite", _sqlite_scan(), "t")
    manifest.update(override)
    return json.dumps(manifest)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", r"^not JSON: "),
        ("[]", r"^not a cortex-backup-manifest document$"),
        (
            _text(format="cortex-memory-export"),
            r"^not a cortex-backup-manifest document$",
        ),
        (_text(version=2), r"^manifest version 2, this Cortex reads 1$"),
        (_text(version="1"), r"^manifest version '1', this Cortex reads 1$"),
        (_text(backend="auto"), r"^unknown backend 'auto'"),
        (_text(entries={}), r"^entries must be a list of objects$"),
        (_text(entries=["wiki"]), r"^entries must be a list of objects$"),
        (
            _text(entries=[{"name": "wiki"}]),
            r"^entries \['wiki'\] do not match the sqlite table$",
        ),
    ],
)
def test_parse_refuses_another_format_version_or_table(text, message):
    with pytest.raises(bm.ManifestError, match=message):
        bm.parse_manifest(text)


def test_parse_refuses_a_manifest_without_entries():
    manifest = json.loads(_text())
    del manifest["entries"]
    with pytest.raises(bm.ManifestError, match=r"^entries must be a list of objects$"):
        bm.parse_manifest(json.dumps(manifest))


# --- parse checks every entry against its spec and its files (review of #960) ---


def _entry_text(name: str, **override) -> str:
    manifest = bm.build_manifest(
        "sqlite",
        _sqlite_scan(wiki=[("methodology/wiki/a.md", DIGEST, 1)]),
        "t",
    )
    entry = next(e for e in manifest["entries"] if e["name"] == name)
    entry.update(override)
    return json.dumps(manifest)


@pytest.mark.parametrize(
    ("name", "override"),
    [
        ("sqlite_store", {"path": "/outside/other.db"}),
        ("sqlite_store", {"kind": "dir"}),
        ("sqlite_store", {"secret": True}),
        ("sqlite_store", {"extra": 1}),
        ("wiki", {"present": False}),
        ("backend_marker", {"files": [{"path": "x", "sha256": DIGEST, "size": 1}]}),
    ],
)
def test_parse_refuses_an_entry_that_differs_from_its_spec_or_files(name, override):
    with pytest.raises(bm.ManifestError, match=rf"^entry {name} "):
        bm.parse_manifest(_entry_text(name, **override))


def test_parse_refuses_unsorted_files():
    manifest = bm.build_manifest(
        "sqlite",
        _sqlite_scan(
            wiki=[
                ("methodology/wiki/a.md", DIGEST, 1),
                ("methodology/wiki/b.md", DIGEST, 1),
            ]
        ),
        "t",
    )
    manifest["entries"][2]["files"].reverse()
    with pytest.raises(
        bm.ManifestError, match=r"^entry wiki differs from the table or its files$"
    ):
        bm.parse_manifest(json.dumps(manifest))


@pytest.mark.parametrize(
    "override",
    [
        {"present": "yes"},
        {"present": None},
        {"files": {}},
        {"files": ["methodology/wiki/a.md"]},
        {"files": [{"path": 1, "sha256": DIGEST, "size": 1}]},
        {"files": [{"path": "methodology/wiki/a.md", "sha256": 1, "size": 1}]},
        {"files": [{"path": "methodology/wiki/a.md", "sha256": DIGEST, "size": 1.0}]},
        {"files": [{"path": "methodology/wiki/a.md", "sha256": DIGEST, "size": True}]},
        {"files": [{"path": "methodology/wiki/a.md", "sha256": DIGEST}]},
    ],
)
def test_parse_refuses_malformed_presence_or_files(override):
    with pytest.raises(
        bm.ManifestError, match=r"^entry wiki: present or files malformed$"
    ):
        bm.parse_manifest(_entry_text("wiki", **override))


def test_parse_refuses_a_required_entry_marked_absent():
    text = _entry_text("sqlite_store", present=False, files=[])
    with pytest.raises(
        bm.ManifestError, match=r"memory\.db is required for a sqlite backup"
    ):
        bm.parse_manifest(text)


def test_parse_accepts_absent_and_present_entries_built_by_the_table():
    text = _entry_text("wiki")
    assert bm.parse_manifest(text) == json.loads(text)


def test_parse_refuses_a_parent_traversal_in_a_file_path():
    text = _entry_text(
        "wiki",
        files=[
            {"path": "methodology/wiki/../../outside.txt", "sha256": DIGEST, "size": 1}
        ],
    )
    with pytest.raises(bm.ManifestError, match=r"is not a canonical relative path$"):
        bm.parse_manifest(text)
