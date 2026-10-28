"""The pinned PostgreSQL + pgvector archives: which this host runs, how installed.

Stdlib only. PostgreSQL comes from theseus-rs/postgresql-binaries at a pinned
tag; pgvector is compiled by this repository's CI (``.github/workflows/
pgvector.yml``: pinned upstream tag and commit, built against that very tree on
a runner of each triple, build provenance attested) and published once as a
prerelease of this repository. Each archive is kept only when its sha256
equals the digest recorded here; anything else raises ``AssetError``. The
PostgreSQL tree is extracted, pgvector's ``lib/`` and ``share/extension/``
are laid over it, and a stamp naming both digests is
written last, so a tree without the stamp is never used.

A host this table has no row for is ``UnsupportedError``: the plugin keeps the
SQLite store there (ADR-1114 records why per platform).

source: ADR-1114
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tarfile
import urllib.request
from pathlib import Path

PG_VERSION = "18.6.0"  # source: ADR-1114 (theseus-rs/postgresql-binaries release)
# pgvector compiled by Cortex CI (.github/workflows/pgvector.yml) from this
# upstream tag, refused unless it resolves to this commit.
# source: ADR-1114 (pgvector/pgvector tag v0.8.7, 2026-10-01)
PGVECTOR_VERSION = "0.8.7"
# source: ADR-1114 (gh api repos/pgvector/pgvector/git/refs/tags/v0.8.7)
PGVECTOR_COMMIT = "f37c13f68b57d2c3472b2214fbcff699d6d34876"
# The release of this repository that holds the archives the workflow built.
PGVECTOR_RELEASE = f"pgvector-v{PGVECTOR_VERSION}-pg{PG_VERSION}"  # source: ADR-1114
# source: ADR-1114 (release download URLs: theseus, and this repository)
PG_URL = "https://github.com/theseus-rs/postgresql-binaries/releases/download/{version}/{name}"
VECTOR_URL = "https://github.com/cdeust/Cortex/releases/download/{tag}/{name}"
# Per Rust target triple, the PostgreSQL then the pgvector archive digest,
# measured 2026-10-17 and equal to the digests both releases publish (pgvector:
# workflow run 39017072528, `gh attestation verify` passes for each archive).
SHA256 = {  # source: ADR-1114
    "aarch64-apple-darwin": (
        "a257bcdb8aa3301a13d6a5bcec48f8c9517045b7cbae71e50788b2615539e95b",
        "33959f25f3ab21f68e029ede739911d4a5c875024bf600ed92925cf3671ab68e",
    ),
    "x86_64-apple-darwin": (
        "f8918fbe747e0d79bda58ad8f8afcf23ac384b847ff3af18856f0825ba54b031",
        "f47275763f0d130c5c7a09795fdd656ba2ceac5dbfc3ee367117c5d7b50a89f7",
    ),
    "x86_64-unknown-linux-gnu": (
        "bb3d09f876b2383e25a8c9ce09e32d185a03656a23d074f5195542b1b1b3ca61",
        "8ed6b93ad7d795099e40fed9013e6bb0bd89b3efd2d178445985076f6c021971",
    ),
    "aarch64-unknown-linux-gnu": (
        "5d2b5e8be9e96bfc3d7f22090057a836ec36d5d092542d8d3b93cc145cf4ee13",
        "ceba223254ee2e54ceb148d720a6627f03d0f7c8aeabcb0799c1835cefbbeda0",
    ),
}
_MACHINES = {
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "x86_64": "x86_64",
    "amd64": "x86_64",
}  # source: ADR-1114
_CHUNK = 1 << 20  # source: ADR-1114 (1 MiB read size; any size gives the same digest)
STAMP = (
    ".cortex-installed.json"  # source: ADR-1114 (written last: the tree is complete)
)


class AssetError(RuntimeError):
    """The pinned archives could not be installed; the message says why."""


class UnsupportedError(AssetError):
    """This host has no pinned archive: the plugin keeps the SQLite store."""


def triple(system: str, machine: str, libc: str) -> str:
    """The target triple of ``platform.system()/machine()`` and the libc name."""
    arch = _MACHINES.get(machine.lower())
    if system == "Darwin" and arch:
        name = f"{arch}-apple-darwin"
    elif system == "Linux" and arch and libc == "glibc":
        name = f"{arch}-unknown-linux-gnu"
    elif system == "Windows":
        raise UnsupportedError(
            "native Windows: the server lifecycle uses POSIX flock, and the "
            "Windows archive does not bundle VCRUNTIME140.dll"
        )
    else:
        raise UnsupportedError(
            f"no pinned PostgreSQL archive for {system} {machine} {libc or 'no libc'}"
        )
    if name not in SHA256:
        raise UnsupportedError(f"no pinned PostgreSQL archive for {name}")
    return name


def host_triple() -> str:
    """The triple of the interpreter running this code (Rosetta reports x86_64)."""
    return triple(platform.system(), platform.machine(), platform.libc_ver()[0])


def tree(dist: Path, target: str) -> Path:
    return dist / f"postgresql-{PG_VERSION}-{target}"


def is_installed(dist: Path, target: str) -> bool:
    """True iff the tree for ``target`` carries the stamp of both pinned digests."""
    stamp = tree(dist, target) / STAMP
    try:
        recorded = json.loads(stamp.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    return recorded == {"postgresql": SHA256[target][0], "pgvector": SHA256[target][1]}


def _download(url: str, target: Path, expected: str) -> None:
    sha = hashlib.sha256()
    try:
        with urllib.request.urlopen(url) as response, target.open("wb") as out:  # noqa: S310 — fixed https URL built from the pinned table
            for block in iter(lambda: response.read(_CHUNK), b""):
                sha.update(block)
                out.write(block)
    except OSError as exc:
        raise AssetError(f"could not download {url}: {exc}") from exc
    if sha.hexdigest() != expected:
        raise AssetError(
            f"{url} has sha256 {sha.hexdigest()}, expected {expected}; refusing it"
        )


def _inside(base: Path, member: tarfile.TarInfo) -> bool:
    """The member, and a link's target, stay under ``base``."""
    resolved = (base / member.name).resolve()
    if not resolved.is_relative_to(base.resolve()):
        return False
    if member.issym() or member.islnk():
        anchor = resolved.parent if member.issym() else base
        return (anchor / member.linkname).resolve().is_relative_to(base.resolve())
    return member.isfile() or member.isdir() or member.issym() or member.islnk()


def _extract(archive: Path, into: Path) -> Path:
    """Extract ``archive`` (one top-level directory) under ``into``; return it."""
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        unsafe = [m.name for m in members if not _inside(into, m)]
        if unsafe:
            raise AssetError(
                f"{archive.name} has members outside its tree: {unsafe[:3]}"
            )
        tar.extractall(into, members=members, **_FILTER)  # noqa: S202 — every member checked by _inside above
    tops = {Path(m.name).parts[0] for m in members}
    if len(tops) != 1:
        raise AssetError(
            f"{archive.name} has {len(tops)} top-level entries, expected 1"
        )
    return into / tops.pop()


# The data filter where this Python has it (3.10.12+, 3.11.4+, 3.12+); the
# members were already checked, so older 3.10/3.11 extract the same tree.
_FILTER = (
    {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
)  # source: PEP 706


def _overlay(vector: Path, pg: Path) -> None:
    """pgvector's library and extension files into the PostgreSQL tree."""
    for sub in ("lib", "share/extension"):
        for item in (vector / sub).iterdir():
            if item.is_file():
                shutil.copy2(item, pg / sub / item.name)


def install(dist: Path, target: str) -> Path:
    """The installed tree for ``target``; downloads and verifies it when absent.

    Precondition: the caller holds the managed root's install lock.
    """
    final = tree(dist, target)
    if is_installed(dist, target):
        return final
    scratch = dist / f".install-{os.getpid()}"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    try:
        pg_sha, vector_sha = SHA256[target]
        pg_name, vector_name = (
            f"postgresql-{PG_VERSION}-{target}.tar.gz",
            f"pgvector-{target}-pg18.tar.gz",
        )
        _download(
            PG_URL.format(version=PG_VERSION, name=pg_name), scratch / pg_name, pg_sha
        )
        _download(
            VECTOR_URL.format(tag=PGVECTOR_RELEASE, name=vector_name),
            scratch / vector_name,
            vector_sha,
        )
        pg = _extract(scratch / pg_name, scratch / "pg")
        _overlay(_extract(scratch / vector_name, scratch / "vector"), pg)
        (pg / STAMP).write_text(
            json.dumps({"postgresql": pg_sha, "pgvector": vector_sha}), encoding="utf-8"
        )
        shutil.rmtree(final, ignore_errors=True)  # an unstamped, partial tree
        os.replace(pg, final)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return final
