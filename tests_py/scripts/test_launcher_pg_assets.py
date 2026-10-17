"""scripts/launcher_pg_assets.py: which archive a host runs, and installing it.

Archives are built locally and served over ``file://``; the digest table is
patched to theirs. Nothing is downloaded.

source: ADR-1110
"""

from __future__ import annotations

import hashlib
import io
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
    ("system", "machine", "libc", "expected"),
    [
        ("Darwin", "arm64", "", "aarch64-apple-darwin"),
        ("Darwin", "x86_64", "", "x86_64-apple-darwin"),
        ("Linux", "x86_64", "glibc", "x86_64-unknown-linux-gnu"),
        ("Linux", "aarch64", "glibc", "aarch64-unknown-linux-gnu"),
    ],
)
def test_each_supported_host_has_a_pinned_archive(
    assets, system, machine, libc, expected
):
    assert assets.triple(system, machine, libc) == expected
    assert expected in assets.SHA256


@pytest.mark.parametrize(
    ("system", "machine", "libc", "why"),
    [
        ("Windows", "AMD64", "", "VCRUNTIME140"),
        ("Linux", "x86_64", "", "no pinned"),  # musl: platform.libc_ver() is empty
        ("Linux", "riscv64", "glibc", "no pinned"),
        ("FreeBSD", "amd64", "", "no pinned"),
    ],
)
def test_every_other_host_keeps_sqlite_with_the_reason(
    assets, system, machine, libc, why
):
    with pytest.raises(assets.UnsupportedError, match=why):
        assets.triple(system, machine, libc)


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


def _serve(monkeypatch, assets, tmp_path, pg_files, vector_files, link=()):
    pg_name = f"postgresql-{assets.PG_VERSION}-{_TARGET}.tar.gz"
    vector_name = f"pgvector-{_TARGET}-pg18.tar.gz"
    pg_sha = _archive(
        tmp_path / pg_name, f"postgresql-{assets.PG_VERSION}-{_TARGET}", pg_files, link
    )
    vector_sha = _archive(
        tmp_path / vector_name, f"pgvector-{_TARGET}-pg18", vector_files
    )
    monkeypatch.setattr(assets, "PG_URL", tmp_path.as_uri() + "/{name}")
    monkeypatch.setattr(assets, "VECTOR_URL", tmp_path.as_uri() + "/{name}")
    monkeypatch.setitem(assets.SHA256, _TARGET, (pg_sha, vector_sha))


_PG = {
    "bin/postgres": b"pg",
    "lib/pg_trgm.dylib": b"t",
    "share/extension/pg_trgm.control": b"c",
}  # source: theseus archive layout
_VECTOR = {
    "lib/vector.dylib": b"v",
    "share/extension/vector.control": b"c",
}  # source: scripts/pgvector_build.py layout (lib/, share/extension/)


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
