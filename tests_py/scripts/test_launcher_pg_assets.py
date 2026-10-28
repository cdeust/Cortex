"""scripts/launcher_pg_assets.py: which archive a host runs, and installing it.

Archives are built locally and served over ``file://``; the digest table is
patched to theirs. Nothing is downloaded.

source: ADR-1114
"""

from __future__ import annotations

import hashlib
import io
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGET = "aarch64-apple-darwin"  # source: launcher_pg_assets.SHA256 keys


@pytest.fixture
def assets(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import launcher_pg_assets

    return launcher_pg_assets


@pytest.mark.parametrize(
    ("system", "machine", "libc", "version", "expected"),
    [
        ("Darwin", "arm64", "", "", "aarch64-apple-darwin"),
        ("Darwin", "x86_64", "", "", "x86_64-apple-darwin"),
        ("Linux", "x86_64", "glibc", "2.39", "x86_64-unknown-linux-gnu"),
        ("Linux", "aarch64", "glibc", "2.36", "aarch64-unknown-linux-gnu"),
        ("Linux", "x86_64", "glibc", "2.43", "x86_64-unknown-linux-gnu"),
    ],
)  # source: glibc of Ubuntu 24.04 (2.39), Debian 12 (2.36), Ubuntu 26.04 (2.43)
def test_each_supported_host_has_a_pinned_archive(
    assets, system, machine, libc, version, expected
):
    assert assets.triple(system, machine, libc, version) == expected
    assert expected in assets.SHA256
    assert expected in assets.PG_VERSIONS


def test_linux_runs_the_release_that_bundles_its_libraries(assets):
    # source: ADR-1114 (theseus 18.6.0 linux-gnu needs the host's libxml2.so.2,
    # absent on Ubuntu 25.10/26.04; 18.6.1 bundles it; macOS keeps 18.6.0)
    assert assets.PG_VERSIONS == {
        "aarch64-apple-darwin": "18.6.0",
        "x86_64-apple-darwin": "18.6.0",
        "x86_64-unknown-linux-gnu": "18.6.1",
        "aarch64-unknown-linux-gnu": "18.6.1",
    }
    assert set(assets.PG_VERSIONS) == set(assets.SHA256)


def test_the_pgvector_release_names_the_tree_it_was_built_against(assets):
    # source: ADR-1114 (published once; a PostgreSQL pin move does not rename it)
    assert assets.PGVECTOR_RELEASE == "pgvector-v0.8.7-pg18.6.0"


def test_the_pgvector_build_uses_the_tree_the_release_was_built_against(
    assets, monkeypatch
):
    # source: ADR-1114 (macOS still runs the 18.6.0 build tree; Linux moved on)
    monkeypatch.setattr(sys, "path", [*sys.path])  # its import edits sys.path
    import pgvector_build

    assert set(pgvector_build.BUILD_TREE_SHA256) == set(assets.SHA256)
    for target, digest in pgvector_build.BUILD_TREE_SHA256.items():
        same_tree = assets.PG_VERSIONS[target] == assets.PGVECTOR_PG_VERSION
        assert (digest == assets.SHA256[target][0]) is same_tree, target
    # source: the 18.6.0 Linux pins of launcher_pg_assets.py before 2026-10-28,
    # equal to the theseus 18.6.0 release digests
    assert pgvector_build.BUILD_TREE_SHA256["x86_64-unknown-linux-gnu"] == (
        "bb3d09f876b2383e25a8c9ce09e32d185a03656a23d074f5195542b1b1b3ca61"
    )
    assert pgvector_build.BUILD_TREE_SHA256["aarch64-unknown-linux-gnu"] == (
        "5d2b5e8be9e96bfc3d7f22090057a836ec36d5d092542d8d3b93cc145cf4ee13"
    )


@pytest.mark.parametrize(
    ("system", "machine", "libc", "version", "why"),
    [
        ("Windows", "AMD64", "", "", "VCRUNTIME140"),
        ("Linux", "x86_64", "", "", "no pinned"),  # musl: platform.libc_ver() is empty
        ("Linux", "riscv64", "glibc", "2.39", "no pinned"),
        ("FreeBSD", "amd64", "", "", "no pinned"),
        ("Linux", "x86_64", "glibc", "2.35", "glibc 2.35 is older than 2.36"),
        ("Linux", "aarch64", "glibc", "2.34", "glibc 2.34 is older than 2.36"),
        ("Linux", "x86_64", "glibc", "", "glibc version is unknown"),
    ],
)  # source: glibc of Ubuntu 22.04 (2.35) and RHEL 9 (2.34), ADR-1114
def test_every_other_host_keeps_sqlite_with_the_reason(
    assets, system, machine, libc, version, why
):
    with pytest.raises(assets.UnsupportedError, match=why):
        assets.triple(system, machine, libc, version)


def _archive(path: Path, top: str, files: dict[str, bytes], link: tuple = ()) -> str:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size, info.mode = len(data), 0o755
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(f"{top}/{link[0]}")
            info.type, info.linkname = tarfile.SYMTYPE, link[1]
            tar.addfile(info)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serve(
    monkeypatch, assets, tmp_path, pg_files, vector_files, link=(), target=_TARGET
):
    top = f"postgresql-{assets.PG_VERSIONS[target]}-{target}"
    pg_name = f"{top}.tar.gz"
    vector_name = f"pgvector-{target}-pg18.tar.gz"
    pg_sha = _archive(tmp_path / pg_name, top, pg_files, link)
    vector_sha = _archive(
        tmp_path / vector_name, f"pgvector-{target}-pg18", vector_files
    )
    monkeypatch.setattr(assets, "PG_URL", tmp_path.as_uri() + "/{name}")
    monkeypatch.setattr(assets, "VECTOR_URL", tmp_path.as_uri() + "/{name}")
    monkeypatch.setitem(assets.SHA256, target, (pg_sha, vector_sha))


_PG = {
    "bin/postgres": b"pg",
    "lib/pg_trgm.dylib": b"t",
    "share/extension/pg_trgm.control": b"c",
}  # source: theseus archive layout
_VECTOR = {
    "lib/vector.dylib": b"v",
    "share/extension/vector.control": b"c",
}  # source: scripts/pgvector_build.py layout (lib/, share/extension/)


def test_a_linux_install_fetches_and_names_its_own_release(
    assets, monkeypatch, tmp_path
):
    # Only the archive named after PG_VERSIONS[linux] (18.6.1) is served: a
    # shared or wrong version in the download name or the tree path fails here.
    linux = "x86_64-unknown-linux-gnu"
    (tmp_path / "srv").mkdir()
    _serve(monkeypatch, assets, tmp_path / "srv", _PG, _VECTOR, target=linux)
    tree = assets.install(tmp_path / "dist", linux)
    assert tree.name == "postgresql-18.6.1-x86_64-unknown-linux-gnu"
    assert assets.is_installed(tmp_path / "dist", linux)


def test_install_overlays_pgvector_and_stamps_the_tree_last(
    assets, monkeypatch, tmp_path
):
    (tmp_path / "srv").mkdir()
    _serve(monkeypatch, assets, tmp_path / "srv", _PG, _VECTOR)
    tree = assets.install(tmp_path / "dist", _TARGET)
    assert (tree / "lib" / "vector.dylib").read_bytes() == b"v"
    assert (tree / "share" / "extension" / "vector.control").is_file()
    assert (tree / "bin" / "postgres").stat().st_mode & 0o100
    assert assets.is_installed(tmp_path / "dist", _TARGET)
    assert [p.name for p in (tmp_path / "dist").iterdir()] == [tree.name]  # no scratch


def test_a_digest_mismatch_is_refused_and_nothing_installed(
    assets, monkeypatch, tmp_path
):
    (tmp_path / "srv").mkdir()
    _serve(monkeypatch, assets, tmp_path / "srv", _PG, _VECTOR)
    monkeypatch.setitem(assets.SHA256, _TARGET, ("0" * 64, assets.SHA256[_TARGET][1]))
    with pytest.raises(assets.AssetError, match="refusing it"):
        assets.install(tmp_path / "dist", _TARGET)
    assert not assets.is_installed(tmp_path / "dist", _TARGET)
    assert list((tmp_path / "dist").iterdir()) == []


def test_a_link_leaving_the_tree_is_refused(assets, monkeypatch, tmp_path):
    (tmp_path / "srv").mkdir()
    _serve(
        monkeypatch,
        assets,
        tmp_path / "srv",
        _PG,
        _VECTOR,
        link=("lib/evil", "../../../etc/passwd"),
    )
    with pytest.raises(assets.AssetError, match="outside its tree"):
        assets.install(tmp_path / "dist", _TARGET)


def test_an_unstamped_tree_is_replaced(assets, monkeypatch, tmp_path):
    (tmp_path / "srv").mkdir()
    _serve(monkeypatch, assets, tmp_path / "srv", _PG, _VECTOR)
    partial = assets.tree(tmp_path / "dist", _TARGET)
    (partial / "bin").mkdir(parents=True)
    (partial / "bin" / "leftover").write_text("x")
    tree = assets.install(tmp_path / "dist", _TARGET)
    assert not (tree / "bin" / "leftover").exists()
    assert assets.is_installed(tmp_path / "dist", _TARGET)
