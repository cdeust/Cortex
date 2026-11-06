"""`cortex doctor` check: which Cortex artifact this process runs (#729, slice 1).

A fix on ``main`` reaches a user only through the artifact their host runs: the
Codex plugin pins an installed wheel by version, the Claude plugin runs the code
of its plugin directory. The 2026-10-10 audit (#729) found v4.23.5 installed
while ``main`` held 42 changed ``mcp_server`` members, so a main-only fix could
not be attributed to the running runtime. This check names the artifact:

- an installed wheel: its version and a digest over the ``mcp_server`` members
  its ``RECORD`` lists, each member re-hashed on disk against that ``RECORD``
  (PEP 376/627: ``RECORD`` holds ``sha256=`` plus the urlsafe base64 digest);
- a source tree (a checkout or an editable install): its git revision, whether
  ``mcp_server`` differs from it, and the same digest computed over its files,
  labelled as source evidence, never as a distributed artifact. In a git
  checkout the files are the ones git keeps in the tree (tracked, or untracked
  and not ignored), so an ignored file such as ``.DS_Store`` does not change
  the digest; hatchling leaves ``.gitignore``-matched files out of the wheel
  too (its default file selection). A tree that is not a git checkout (no
  ``.git``) has no revision: it is named as such and its digest covers every
  file under the package.

The digest is one sha256 over the sorted ``path,sha256=...`` lines, so a wheel
and the source tree it was built from give the same value (hatchling ships the
``mcp_server`` package: pyproject ``[tool.hatch.build.targets.wheel]``).

source: issue #729 (acceptance: record source revision and installed artifact
digests in diagnostics; keep main-only evidence separately labelled)
"""

from __future__ import annotations

import base64
import csv
import hashlib
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Iterable

import mcp_server
from mcp_server.shared.subprocess_safe import run_with_hard_timeout

NAME = "Runtime artifact identity"  # source: issue #729 (title: artifact identity)
DISTRIBUTION = "hypermnesia-mcp"  # source: pyproject.toml [project] name
PACKAGE = "mcp_server"  # source: pyproject.toml [tool.hatch.build.targets.wheel]
# source: doctor.py _WORKTREE_LIST_TIMEOUT_S (validate_memory.py:29 precedent)
_GIT_TIMEOUT_S = 2.0
# source: plugins/hypermnesia-mcp-codex/scripts/runtime.py main(): `setup` runs
# `uv tool install --python <interpreter> --no-build`, the interpreter pinned
# because uv once picked Intel CPython on an ARM host (runtime.py docstring,
# 2026-10-02). A plain `runtime.py setup` keeps an installed version as it is,
# so the fix adds --reinstall and names the interpreter running this process.
_REINSTALL = (
    "Reinstall the runtime: `uv tool install --reinstall --python {python} "
    '--no-build "hypermnesia-mcp[postgresql,sqlite]=={version}"` (Codex) or '
    "reinstall the plugin (Claude)"
)


def record_hash(data: bytes) -> str:
    """The RECORD form of a file digest: ``sha256=`` + urlsafe b64, unpadded
    (32 bytes encode to 43 characters and one ``=``: RFC 4648 section 4)."""
    raw = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(raw).removesuffix(b"=").decode()


def members_digest(members: Iterable[tuple[str, str]]) -> str:
    """One sha256 over the sorted ``path,hash`` lines of ``members``."""
    lines = sorted(f"{path},{digest}" for path, digest in members)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def tree_members(
    root: Path, listed: Iterable[str] | None = None
) -> list[tuple[str, str]]:
    """The files of the package ``root`` except bytecode, RECORD-style.

    ``listed`` holds the package files as paths relative to ``root.parent``
    (git's answer in a checkout); ``None`` means every file under ``root``.
    A listed path absent from disk (deleted but still tracked) is skipped."""
    if listed is None:
        paths = root.rglob("*")
    else:
        paths = (root.parent / name for name in listed)
    members = []
    for path in sorted(set(paths)):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = f"{PACKAGE}/{path.relative_to(root).as_posix()}"
        members.append((relative, record_hash(path.read_bytes())))
    return members


def wheel_members(dist: Any) -> list[tuple[str, str]]:
    """The hashed ``mcp_server`` rows of ``dist``'s RECORD (empty if editable).

    RECORD is read as written: from Python 3.12, ``Distribution.files`` omits
    the files absent from disk, which would hide a deleted member."""
    rows = []
    for row in csv.reader((dist.read_text("RECORD") or "").splitlines()):
        if not row:
            continue
        path, digest, *_ = row
        if digest and path.startswith(f"{PACKAGE}/"):
            rows.append((path, digest))
    return rows


def _installed(check: Callable[..., Any], dist: Any, rows: list) -> Any:
    altered = []
    for path, expected in rows:
        file = Path(str(dist.locate_file(path)))
        if not file.is_file() or record_hash(file.read_bytes()) != expected:
            altered.append(path)
    detail = (
        f"installed {DISTRIBUTION} {dist.version}, {len(rows)} {PACKAGE} "
        f"members, digest {members_digest(rows)}"
    )
    if altered:
        detail += f"; {len(altered)} differ from its RECORD, first {altered[0]}"
        return check(NAME, False, detail, _reinstall(dist.version), optional=True)
    return check(NAME, True, detail, optional=True)


def _reinstall(version: str) -> str:
    python = Path(sys.executable).resolve()
    return _REINSTALL.format(python=python, version=version)


def _git(root: Path, *argv: str) -> str | None:
    return run_with_hard_timeout(["git", *argv], cwd=root, timeout=_GIT_TIMEOUT_S)


def _tree_detail(root: Path, where: str, version: str, members: list) -> str:
    return (
        f"source tree {root.parent} {where} (version {version}), "
        f"{len(members)} {PACKAGE} files, digest {members_digest(members)}; "
        "source evidence, not a distributed artifact"
    )


def _source_tree(check: Callable[..., Any], root: Path, version: str) -> Any:
    if not (root.parent / ".git").exists():
        # No repository to ask: the digest is the tree's only identity.
        detail = _tree_detail(root, "outside git", version, tree_members(root))
        return check(NAME, True, detail, optional=True)
    revision = _git(root.parent, "rev-parse", "HEAD") or "no git revision"
    changes = _git(root.parent, "status", "--porcelain", "--", PACKAGE)
    listed = _git(
        root.parent,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        PACKAGE,
    )
    names = None if listed is None else [n for n in listed.split("\0") if n]
    state = " with uncommitted changes" if changes else ""
    members = tree_members(root, names)
    detail = _tree_detail(root, f"at {revision}{state}", version, members)
    if changes is None or names is None:
        # git failed or timed out: the tree is not known to match the revision,
        # and its file list falls back to every file under the package.
        failed = "status" if changes is None else "ls-files"
        detail += f"; revision state unknown: `git {failed}` failed"
        fix = f"Run `git -C {root.parent} {failed}` to see why git cannot answer"
        return check(NAME, False, detail, fix, optional=True)
    return check(NAME, True, detail, optional=True)


def artifact_identity(check: Callable[..., Any]) -> Any:
    """Name the artifact this process imports ``mcp_server`` from.

    Pre-condition: ``check`` is doctor's ``Check`` constructor.
    Post-condition: an optional check; it fails when an installed wheel's
    files differ from its own RECORD or its RECORD is gone, when git cannot
    state a checkout's revision state or file list, or when a file or RECORD
    cannot be read (the failure names
    it; the other doctor checks still run)."""
    try:
        return _identify(check)
    except (OSError, RuntimeError, ValueError) as exc:
        # Path.resolve() raises RuntimeError on a symlink loop up to Python
        # 3.12 (OSError from 3.13): either is this check's failure, not doctor's.
        return check(
            NAME, False, f"cannot read the running artifact: {exc}", optional=True
        )


def _identify(check: Callable[..., Any]) -> Any:
    root = Path(mcp_server.__file__).resolve().parent
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return _source_tree(check, root, "unknown")
    if Path(str(dist.locate_file(PACKAGE))).resolve() != root:
        return _source_tree(check, root, dist.version)
    if dist.read_text("RECORD") is None:
        # An installed wheel whose RECORD is gone cannot be checked against
        # anything; describing it as a source tree would hide that.
        detail = f"installed {DISTRIBUTION} {dist.version} has no RECORD"
        fix = _reinstall(dist.version)
        return check(NAME, False, detail, fix, optional=True)
    rows = wheel_members(dist)
    if rows:
        return _installed(check, dist, rows)
    return _source_tree(check, root, dist.version)
