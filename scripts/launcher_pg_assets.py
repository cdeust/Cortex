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

# The theseus-rs/postgresql-binaries release each triple runs. Linux GNU runs
# 18.6.1, the first release that bundles its runtime libraries (theseus commit
# 78f15cec): 18.6.0 needs the host's libxml2.so.2, which Ubuntu 25.10 and 26.04
# do not ship, and 18.6.1's bundled libstdc++ needs glibc 2.36. macOS keeps
# 18.6.0, whose only host library is the system libxml2 (13 MB, not 90 MB).
PG_VERSIONS = {  # source: ADR-1114
    "aarch64-apple-darwin": "18.6.0",
    "x86_64-apple-darwin": "18.6.0",
    "x86_64-unknown-linux-gnu": "18.6.1",
    "aarch64-unknown-linux-gnu": "18.6.1",
}
# The oldest glibc the Linux GNU 18.6.1 tree loads on: its bundled libstdc++.so.6
# references GLIBC_2.36 (Ubuntu 22.04's 2.35 fails, Debian 12's 2.36 runs;
# measured 2026-10-28). Older hosts are refused before the 40 MB download.
GLIBC_FLOOR = (2, 36)  # source: ADR-1114
# pgvector compiled by Cortex CI (.github/workflows/pgvector.yml) from this
# upstream tag, refused unless it resolves to this commit.
# source: ADR-1114 (pgvector/pgvector tag v0.8.7, 2026-10-01)
PGVECTOR_VERSION = "0.8.7"
# source: ADR-1114 (gh api repos/pgvector/pgvector/git/refs/tags/v0.8.7)
PGVECTOR_COMMIT = "f37c13f68b57d2c3472b2214fbcff699d6d34876"
# The PostgreSQL tree the published pgvector archives were compiled against
# (PGXS, every triple). They load unchanged into theseus 18.6.1, which packages
# the same PostgreSQL 18.6 source: CREATE EXTENSION vector and a distance pass
# on Ubuntu 26.04 (aarch64, and x86_64 under emulation), Ubuntu 24.04 and
# Debian 12 (aarch64), measured 2026-10-28.
PGVECTOR_PG_VERSION = "18.6.0"  # source: ADR-1114
# The release of this repository that holds the archives the workflow built.
PGVECTOR_RELEASE = (
    f"pgvector-v{PGVECTOR_VERSION}-pg{PGVECTOR_PG_VERSION}"  # source: ADR-1114
)
# source: ADR-1114 (release download URLs: theseus, and this repository)
PG_URL = "https://github.com/theseus-rs/postgresql-binaries/releases/download/{version}/{name}"
VECTOR_URL = "https://github.com/cdeust/Cortex/releases/download/{tag}/{name}"
# Per Rust target triple, the PostgreSQL (release PG_VERSIONS names) then the
# pgvector archive digest, equal to the digests both releases publish (pgvector:
# workflow run 39017072528, `gh attestation verify` passes for each archive).
# Measured 2026-10-17; the two Linux PostgreSQL digests (18.6.1) 2026-10-28.
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
        "e84b02dd8d0ce5879fb697330a789231c8b8f8d958dae3ad4d90fecc710b1315",
        "8ed6b93ad7d795099e40fed9013e6bb0bd89b3efd2d178445985076f6c021971",
    ),
    "aarch64-unknown-linux-gnu": (
        "1ab47fa2f06ff70454309ad02e5d89c46488300d43977231481fd6b160b9d556",
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


def _glibc_at_least_floor(version: str) -> bool:
    head = version.split(".")[: len(GLIBC_FLOOR)]
    if len(head) < len(GLIBC_FLOOR) or not all(part.isdigit() for part in head):
        return False
    return tuple(int(part) for part in head) >= GLIBC_FLOOR


def _glibc_refusal(version: str, pg_version: str) -> str:
    floor = ".".join(map(str, GLIBC_FLOOR))
    if not version:
        return (
            f"the glibc version is unknown here, and PostgreSQL {pg_version} "
            f"needs glibc {floor} (GLIBC_{floor})"
        )
    return (
        f"glibc {version} is older than {floor}, which PostgreSQL {pg_version} "
        f"needs (GLIBC_{floor})"
    )


def triple(system: str, machine: str, libc: str, libc_version: str) -> str:
    """The target triple of ``platform.system()/machine()/libc_ver()``."""
    arch = _MACHINES.get(machine.lower())
    if system == "Darwin" and arch:
        name = f"{arch}-apple-darwin"
    elif system == "Linux" and arch and libc == "glibc":
        name = f"{arch}-unknown-linux-gnu"
        if not _glibc_at_least_floor(libc_version):
            raise UnsupportedError(_glibc_refusal(libc_version, PG_VERSIONS[name]))
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
    libc, libc_version = platform.libc_ver()
    return triple(platform.system(), platform.machine(), libc, libc_version)


def tree(dist: Path, target: str) -> Path:
    return dist / f"postgresql-{PG_VERSIONS[target]}-{target}"


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
        version = PG_VERSIONS[target]
        pg_name, vector_name = (
            f"postgresql-{version}-{target}.tar.gz",
            f"pgvector-{target}-pg18.tar.gz",
        )
        _download(
            PG_URL.format(version=version, name=pg_name), scratch / pg_name, pg_sha
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
