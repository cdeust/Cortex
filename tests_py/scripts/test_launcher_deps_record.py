"""Tests for scripts/launcher_deps_record.py and the guard that reads it.

Issue #575: the owners of a top-level deps entry come from each
distribution's ``RECORD``, never from the entry's name. The row shapes below
are the ones measured on the maintainer's 4.22.0 deps directory on
2026-09-15 (``yaml``/``_yaml`` in PyYAML's RECORD, ``../../bin/...`` script
rows, a top-level ``__pycache__`` listed by several distributions).

source: ADR-1064"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"scripts.{name}", SCRIPTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def record_mod():
    return _load("launcher_deps_record")


@pytest.fixture
def install_mod():
    return _load("launcher_deps_install")


def _dist_info(root: Path, dir_name: str, rows: list[str]) -> Path:
    d = root / dir_name
    d.mkdir(parents=True)
    (d / "RECORD").write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")
    return d


@pytest.mark.parametrize(
    ("path", "entry"),
    [
        ("yaml/__init__.py", "yaml"),
        ("six.py", "six.py"),
        ("pyyaml-6.0.3.dist-info/RECORD", "pyyaml-6.0.3.dist-info"),
        ("../../bin/tqdm", "bin"),
        ("../../share/man/man1/isympy.1", "share"),
        ("../../../bin/tqdm", None),
        ("../outside.py", None),
        ("/usr/lib/python3/x.py", None),
        ("", None),
    ],
)
def test_record_top_level(record_mod, path, entry) -> None:
    assert record_mod.record_top_level(path) == entry


def test_entry_owners_maps_import_names_to_their_distribution(
    record_mod, tmp_path
) -> None:
    _dist_info(
        tmp_path,
        "pyyaml-6.0.3.dist-info",
        [
            "_yaml/__init__.py,sha256=x,1",
            "yaml/__init__.py,sha256=y,2",
            "pyyaml-6.0.3.dist-info/RECORD,,",
        ],
    )
    owners = record_mod.entry_owners(str(tmp_path))
    assert owners == {
        "_yaml": frozenset({"pyyaml"}),
        "yaml": frozenset({"pyyaml"}),
        "pyyaml-6.0.3.dist-info": frozenset({"pyyaml"}),
    }


def test_entry_owners_lists_every_distribution_sharing_an_entry(
    record_mod, tmp_path
) -> None:
    _dist_info(
        tmp_path,
        "protobuf-7.36.1.dist-info",
        ["google/protobuf/__init__.py,,", "../../bin/protoc-shim,,"],
    )
    _dist_info(
        tmp_path,
        "googleapis_common_protos-1.70.0.dist-info",
        ["google/api/__init__.py,,", "../../bin/api-shim,,"],
    )
    owners = record_mod.entry_owners(str(tmp_path))
    both = frozenset({"protobuf", "googleapis_common_protos"})
    assert owners["google"] == both
    assert owners["bin"] == both


def test_entry_owners_skips_a_missing_or_undecodable_record(
    record_mod, tmp_path
) -> None:
    (tmp_path / "norecord-1.0.dist-info").mkdir()
    broken = tmp_path / "broken-1.0.dist-info"
    broken.mkdir()
    (broken / "RECORD").write_bytes(b"\xff\xfe\x00bad")
    (tmp_path / "norecord").mkdir()
    assert record_mod.entry_owners(str(tmp_path)) == {}


def test_entry_owners_of_a_missing_directory_is_empty(record_mod, tmp_path) -> None:
    assert record_mod.entry_owners(str(tmp_path / "absent")) == {}


def test_guard_never_satisfies_an_entry_no_record_owns(install_mod, tmp_path) -> None:
    (tmp_path / "yaml").mkdir()
    assert not install_mod._entry_already_satisfied(
        "yaml", frozenset(), {"pyyaml": "6.0.3"}, {"pyyaml": "6.0.3"}, str(tmp_path)
    )


def test_guard_requires_every_owner_at_the_resolved_version(
    install_mod, tmp_path
) -> None:
    (tmp_path / "google").mkdir()
    owners = frozenset({"protobuf", "googleapis_common_protos"})
    resolved = {"protobuf": "7.36.1", "googleapis_common_protos": "1.70.0"}
    satisfied = install_mod._entry_already_satisfied
    assert satisfied("google", owners, resolved, dict(resolved), str(tmp_path))
    stale = {**resolved, "googleapis_common_protos": "1.69.0"}
    assert not satisfied("google", owners, resolved, stale, str(tmp_path))
    missing = {"protobuf": "7.36.1"}
    assert not satisfied("google", owners, resolved, missing, str(tmp_path))
