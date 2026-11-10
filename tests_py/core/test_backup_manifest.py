"""The pure backup manifest: resource table, build and parse (issue #731, slice 2)."""

from __future__ import annotations


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


# --- resource table ---------------------------------------------------------


def test_sqlite_table_is_the_audit_class_a_set():
    assert [
        (s.name, s.path, s.kind, s.required, s.secret)
        for s in bm.resources_for("sqlite")
    ] == [
        ("sqlite_store", "methodology/memory.db", "file", True, False),
        ("backend_marker", "methodology/backend.json", "file", False, False),
        ("wiki", "methodology/wiki", "dir", False, False),
        ("artifacts", "methodology/artifacts", "dir", False, False),
        ("mcp_connections", "methodology/mcp-connections.json", "file", False, False),
        ("profile_domains", "methodology/domains", "dir", False, False),
        ("profile_index", "methodology/index.json", "file", False, False),
        ("legacy_profiles", "methodology/profiles.json", "file", False, False),
        (
            "legacy_profiles_backup",
            "methodology/profiles.json.v1_backup",
            "file",
            False,
            False,
        ),
        ("session_log", "methodology/session-log.json", "file", False, False),
        ("capture_spool", ".capture-worker/spool", "dir", False, False),
    ]


def test_managed_table_carries_cluster_and_secret_password_not_sqlite_file():
    specs = {s.name: s for s in bm.resources_for("managed")}
    assert "sqlite_store" not in specs
    assert (specs["managed_cluster"].path, specs["managed_cluster"].kind) == (
        "methodology/managed-pg/cluster",
        "dir",
    )
    assert specs["managed_cluster"].required and not specs["managed_cluster"].secret
    password = specs["managed_password"]
    assert (password.path, password.kind, password.required, password.secret) == (
        "methodology/managed-pg/password",
        "file",
        True,
        True,
    )
    assert len(specs) == 12


def test_user_postgresql_table_has_no_store_entry_and_nothing_required():
    specs = bm.resources_for("postgresql")
    assert len(specs) == 10
    assert not any(s.required for s in specs)
    assert not {"sqlite_store", "managed_cluster", "managed_password"} & {
        s.name for s in specs
    }


def test_backends_are_the_marker_values():
    assert bm.BACKENDS == {"sqlite", "managed", "postgresql"}
    assert (bm.SQLITE, bm.MANAGED, bm.POSTGRESQL) == ("sqlite", "managed", "postgresql")


def test_unknown_backend_is_refused():
    with pytest.raises(
        bm.ManifestError, match=r"unknown backend 'auto'; expected one of"
    ):
        bm.resources_for("auto")


# --- build --------------------------------------------------------------------


def test_build_writes_format_version_backend_and_every_entry_in_table_order():
    manifest = bm.build_manifest(
        "sqlite",
        _sqlite_scan(
            wiki=[
                ("methodology/wiki/b.md", OTHER, 2),
                ("methodology/wiki/a.md", DIGEST, 1),
            ]
        ),
        "2026-11-10T03:00:00+00:00",
    )
    assert manifest["format"] == "cortex-backup-manifest"
    assert manifest["version"] == 1
    assert manifest["created_at"] == "2026-11-10T03:00:00+00:00"
    assert manifest["backend"] == "sqlite"
    assert [e["name"] for e in manifest["entries"]] == [
        s.name for s in bm.resources_for("sqlite")
    ]
    store, wiki, marker = (manifest["entries"][i] for i in (0, 2, 1))
    assert store == {
        "name": "sqlite_store",
        "path": "methodology/memory.db",
        "kind": "file",
        "secret": False,
        "present": True,
        "files": [{"path": "methodology/memory.db", "sha256": DIGEST, "size": 10}],
    }
    assert [f["path"] for f in wiki["files"]] == [
        "methodology/wiki/a.md",
        "methodology/wiki/b.md",
    ]
    assert marker["present"] is False and marker["files"] == []


def test_an_empty_present_directory_is_present_with_no_files():
    entry = bm.build_manifest("sqlite", _sqlite_scan(artifacts=[]), "t")["entries"][3]
    assert entry["name"] == "artifacts"
    assert entry["present"] is True and entry["files"] == []


def test_secret_flag_reaches_the_entry():
    scan = _scan(
        "managed",
        managed_cluster=[],
        managed_password=[("methodology/managed-pg/password", DIGEST, 0)],
    )
    entries = {e["name"]: e for e in bm.build_manifest("managed", scan, "t")["entries"]}
    assert entries["managed_password"]["secret"] is True
    assert entries["managed_cluster"]["secret"] is False


def test_a_required_absent_resource_is_refused():
    with pytest.raises(
        bm.ManifestError,
        match=r"^methodology/memory\.db is required for a sqlite backup and is absent$",
    ):
        bm.build_manifest("sqlite", _scan("sqlite"), "t")


def test_an_optional_absent_resource_is_not_refused():
    manifest = bm.build_manifest("postgresql", _scan("postgresql"), "t")
    assert all(e["present"] is False for e in manifest["entries"])


@pytest.mark.parametrize(
    "scanned",
    [
        lambda: {k: v for k, v in _sqlite_scan().items() if k != "wiki"},
        lambda: {**_sqlite_scan(), "managed_cluster": None},
    ],
)
def test_a_scan_with_a_missing_or_extra_name_is_refused(scanned):
    with pytest.raises(
        bm.ManifestError, match=r"^scan names \[.*\], the sqlite table names \["
    ):
        bm.build_manifest("sqlite", scanned(), "t")


@pytest.mark.parametrize(
    "records",
    [
        [],
        [("methodology/other.db", DIGEST, 1)],
        [("methodology/memory.db", DIGEST, 1)] * 2,
    ],
)
def test_a_file_resource_takes_exactly_its_own_path(records):
    with pytest.raises(
        bm.ManifestError,
        match=r"^methodology/memory\.db is a file resource: one record, its own path$",
    ):
        bm.build_manifest("sqlite", _scan("sqlite", sqlite_store=records), "t")


@pytest.mark.parametrize(
    "path", ["methodology/wikix/a.md", "methodology/wiki", "elsewhere/a.md"]
)
def test_a_directory_record_outside_its_resource_is_refused(path):
    with pytest.raises(
        bm.ManifestError, match=rf"^{path} is not inside methodology/wiki$"
    ):
        bm.build_manifest("sqlite", _sqlite_scan(wiki=[(path, DIGEST, 1)]), "t")


@pytest.mark.parametrize(
    ("sha256", "size"),
    [("A" * 64, 1), ("a" * 63, 1), ("a" * 65, 1), ("g" * 64, 1), (DIGEST, -1)],
)
def test_an_invalid_digest_or_size_is_refused(sha256, size):
    with pytest.raises(
        bm.ManifestError, match=r"^methodology/wiki/a\.md: invalid digest or size$"
    ):
        bm.build_manifest(
            "sqlite", _sqlite_scan(wiki=[("methodology/wiki/a.md", sha256, size)]), "t"
        )


def test_size_zero_is_valid():
    entry = bm.build_manifest(
        "sqlite", _sqlite_scan(wiki=[("methodology/wiki/a.md", DIGEST, 0)]), "t"
    )
    assert entry["entries"][2]["files"][0]["size"] == 0


@pytest.mark.parametrize(
    "path",
    [
        "methodology/wiki/../../outside.txt",
        "methodology/wiki/./a.md",
        "methodology/wiki//a.md",
        "methodology/wiki/a.md/",
        "/methodology/wiki/a.md",
        "methodology/wiki/sub\\..\\..\\x",
        "methodology/wiki/..",
    ],
)
def test_a_path_that_is_not_canonical_is_refused(path):
    with pytest.raises(bm.ManifestError, match=r"is not a canonical relative path$"):
        bm.build_manifest("sqlite", _sqlite_scan(wiki=[(path, DIGEST, 1)]), "t")


def test_dots_inside_a_name_are_canonical():
    records = [
        ("methodology/wiki/..a.md", DIGEST, 1),
        ("methodology/wiki/a..b/.c", DIGEST, 1),
    ]
    entry = bm.build_manifest("sqlite", _sqlite_scan(wiki=records), "t")["entries"][2]
    assert [f["path"] for f in entry["files"]] == [r[0] for r in records]
