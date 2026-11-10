"""`cortex doctor` check: which Cortex artifact this process runs (#729, slice 1).

A fix on ``main`` reaches a user only through the artifact their host runs: the
Codex plugin pins an installed wheel by version, the Claude plugin runs the code
of its plugin directory. The 2026-10-10 audit (#729) found v4.23.5 installed
while ``main`` held 42 changed ``mcp_server`` members, so a main-only fix could
not be attributed to the running runtime. This check names the artifact:

- an installed wheel: its version and a digest over the ``mcp_server`` members
  its ``RECORD`` lists, each member re-hashed on disk against that ``RECORD``
  (PEP 376/627: ``RECORD`` holds ``sha256=`` plus the urlsafe base64 digest),
  and any package file the ``RECORD`` does not list counted as a difference
  too: an unlisted ``.py``, extension or sourceless ``.pyc`` would run while
  the digest still matched (Codex security review on #957). Bytecode under
  ``__pycache__`` is not counted, since Python writes it at import;
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
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Identity:
    """The running ``mcp_server`` as data: the check and a receipt both read it.

    ``kind`` is ``wheel`` or ``source-tree``; ``version`` is ``None`` when no
    installed distribution names one; ``revision`` is the git sha of a checkout
    (``None`` for a wheel, a tree outside git or a checkout without a commit);
    ``modified`` says ``mcp_server`` differs from what names it (a wheel's
    RECORD, a checkout's revision); ``unknown`` says why the identity cannot be
    stated, with ``fix`` the repair the check prints."""

    kind: str
    version: str | None
    revision: str | None
    modified: bool
    members: tuple[tuple[str, str], ...]
    location: Path
    in_git: bool = False
    altered: tuple[str, ...] = ()
    unknown: str | None = None
    fix: str | None = None

    @property
    def digest(self) -> str:
        return members_digest(self.members)


def _reinstall(version: str) -> str:
    python = Path(sys.executable).resolve()
    return _REINSTALL.format(python=python, version=version)


def _git(root: Path, *argv: str) -> str | None:
    return run_with_hard_timeout(["git", *argv], cwd=root, timeout=_GIT_TIMEOUT_S)


def unrecorded(root: Path, listed: set[str]) -> list[str]:
    """The files under the package ``root`` absent from ``listed`` (RECORD
    paths), bytecode under ``__pycache__`` aside: Python writes it at import."""
    found = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and "__pycache__" not in relative.parts:
            name = f"{PACKAGE}/{relative.as_posix()}"
            if name not in listed:
                found.append(name)
    return found


def _wheel(dist: Any, rows: list, root: Path, record: str) -> Identity:
    altered = []
    for path, expected in rows:
        file = Path(str(dist.locate_file(path)))
        if not file.is_file() or record_hash(file.read_bytes()) != expected:
            altered.append(path)
    listed = {row[0] for row in csv.reader(record.splitlines()) if row}
    altered += unrecorded(root, listed)
    fix = _reinstall(dist.version) if altered else None
    return Identity(
        "wheel", dist.version, None, bool(altered), tuple(rows), root,
        altered=tuple(altered), fix=fix,
    )  # fmt: skip


def _source_tree(root: Path, version: str | None) -> Identity:
    if not (root.parent / ".git").exists():
        # No repository to ask: the digest is the tree's only identity.
        members = tuple(tree_members(root))
        return Identity("source-tree", version, None, False, members, root)
    revision = _git(root.parent, "rev-parse", "HEAD")
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
    members = tuple(tree_members(root, names))
    unknown = fix = None
    if changes is None or names is None:
        # git failed or timed out: the tree is not known to match the revision,
        # and its file list falls back to every file under the package.
        failed = "status" if changes is None else "ls-files"
        unknown = f"revision state unknown: `git {failed}` failed"
        fix = f"Run `git -C {root.parent} {failed}` to see why git cannot answer"
    return Identity(
        "source-tree", version, revision or None, bool(changes), members, root,
        in_git=True, unknown=unknown, fix=fix,
    )  # fmt: skip


def identify() -> Identity:
    """Identify the artifact this process imports ``mcp_server`` from.

    Raises ``OSError``, ``RuntimeError`` or ``ValueError`` when a file, a RECORD
    or the package path cannot be read (a symlink loop: ``RuntimeError`` up to
    Python 3.12; from 3.13 only ``strict=True`` raises, so it is resolved so)."""
    root = Path(mcp_server.__file__).parent.resolve(strict=True)
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return _source_tree(root, None)
    if Path(str(dist.locate_file(PACKAGE))).resolve() != root:
        return _source_tree(root, dist.version)
    record = dist.read_text("RECORD")
    if record is None:
        # An installed wheel whose RECORD is gone cannot be checked against
        # anything; describing it as a source tree would hide that.
        unknown = f"installed {DISTRIBUTION} {dist.version} has no RECORD"
        return Identity(
            "wheel", dist.version, None, False, (), root,
            unknown=unknown, fix=_reinstall(dist.version),
        )  # fmt: skip
    rows = wheel_members(dist)
    if rows:
        return _wheel(dist, rows, root, record)
    return _source_tree(root, dist.version)


def _detail(found: Identity) -> str:
    count = len(found.members)
    if found.kind == "wheel":
        if found.unknown:  # only a wheel without RECORD: it has no members
            return found.unknown
        detail = (
            f"installed {DISTRIBUTION} {found.version}, {count} {PACKAGE} "
            f"members, digest {found.digest}"
        )
        if found.altered:
            detail += (
                f"; {len(found.altered)} differ from its RECORD, "
                f"first {found.altered[0]}"
            )
        return detail
    where = "outside git"
    if found.in_git:
        state = " with uncommitted changes" if found.modified else ""
        where = f"at {found.revision or 'no git revision'}{state}"
    detail = (
        f"source tree {found.location.parent} {where} (version "
        f"{found.version or 'unknown'}), {count} {PACKAGE} files, digest "
        f"{found.digest}; source evidence, not a distributed artifact"
    )
    return detail + (f"; {found.unknown}" if found.unknown else "")


def artifact_identity(check: Callable[..., Any]) -> Any:
    """Name the artifact this process imports ``mcp_server`` from.

    Pre-condition: ``check`` is doctor's ``Check`` constructor.
    Post-condition: an optional check; it fails when an installed wheel's
    files differ from its own RECORD or its RECORD is gone, when git cannot
    state a checkout's revision state or file list, or when a file or RECORD
    cannot be read (the failure names it; the other doctor checks still run)."""
    try:
        found = identify()
    except (OSError, RuntimeError, ValueError) as exc:
        # A symlink loop is this check's failure, not doctor's.
        return check(
            NAME, False, f"cannot read the running artifact: {exc}", optional=True
        )
    if found.fix:
        return check(NAME, False, _detail(found), found.fix, optional=True)
    return check(NAME, True, _detail(found), optional=True)
