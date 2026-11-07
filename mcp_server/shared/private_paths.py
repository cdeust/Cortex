"""Owner-only storage for Cortex's personal data.

Everything Cortex keeps about the user lives under a few roots: the
methodology directory (database, logs, telemetry, wiki, artifacts, profiles),
the capture worker's runtime directory, ``brain-index.json`` and
``~/.cache/cortex`` (upstream MCP logs, the viz registry). On POSIX a file
under them is created ``0600`` and a directory ``0700`` (``gated_files``, the
rotating log, the SQLite file, whose WAL and shared-memory files take its
mode); on Windows the roots carry an ACL granting only the current user, which
files and directories inherit.

Installs made before this existed hold ``0644``/``0755`` (umask) files:
:func:`harden_private_storage` tightens them once per install (a stamp file
records it), and the roots themselves on every call.

No mode is ever changed through a symbolic link. Each entry is opened with
``O_NOFOLLOW`` (a directory also with ``O_DIRECTORY``), checked to be the
entry ``lstat`` saw, and changed with ``fchmod`` on that descriptor; the
tree walk is ``os.fwalk(follow_symlinks=False)``, which works on directory
descriptors. A root that is itself a symbolic link is left as it is and
reported (:func:`symlinked_roots`): what it points to is not Cortex's to
change. The roots' parents (``~/.claude`` and above) are the user's layout
and are resolved as usual.

source: ADR-1112"""

from __future__ import annotations

import errno
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from mcp_server.shared.platform import cache_dir

PRIVATE_FILE_MODE = 0o600  # source: ADR-1112 (owner read/write)
# source: ADR-1112 — open flags that refuse a symlink and never block (FIFO)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
PRIVATE_DIR_MODE = 0o700  # source: ADR-1112 (owner only)
# source: ADR-1112 — bump to re-run the one-time tightening on every install
_STAMP_NAME = ".private-modes-v1"


def claude_root() -> Path:
    override = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".claude"


def cortex_cache_dir() -> Path:
    """Cortex's cache root: session registry, groomer coordination, upstream
    MCP logs. ``CORTEX_CACHE_DIR`` wins; then ``XDG_CACHE_HOME``; then, when
    ``CORTEX_CLAUDE_DIR`` relocates Cortex's data, a ``cache`` directory inside
    it (everything derived from that root follows it); else ``~/.cache``."""
    override = os.environ.get("CORTEX_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.environ.get("XDG_CACHE_HOME") or not os.environ.get("CORTEX_CLAUDE_DIR"):
        return cache_dir() / "cortex"
    return claude_root() / "cache" / "cortex"


def private_roots() -> tuple[Path, ...]:
    """Directories whose whole content is Cortex personal data."""
    root = claude_root()
    return (root / "methodology", root / ".capture-worker", cortex_cache_dir())


def private_files() -> tuple[Path, ...]:
    return (claude_root() / "brain-index.json",)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def is_private(path: str | Path) -> bool:
    """True when ``path`` is, or is inside, Cortex personal-data storage."""
    target = _absolute(Path(path))
    if target in {_absolute(p) for p in private_files()}:
        return True
    return any(
        target == r or r in target.parents for r in map(_absolute, private_roots())
    )


def _owning_root(path: Path) -> Path | None:
    target = _absolute(path)
    for root in map(_absolute, private_roots()):
        if target == root or root in target.parents:
            return root
    return None


def ensure_private_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents); every level from its private root down
    is owner-only. A level that is a symbolic link stops the tightening:
    neither it nor what lies below it is changed. Outside the private roots
    this is a plain ``mkdir -p``."""
    directory = _absolute(Path(path))
    directory.mkdir(parents=True, exist_ok=True)
    root = _owning_root(directory)
    if root is None or sys.platform == "win32":
        return directory
    levels = [directory, *directory.parents]
    for level in reversed(levels[: levels.index(root) + 1]):
        info = os.lstat(level)
        if not stat.S_ISDIR(info.st_mode):
            break
        _tighten(level, info)
    return directory


def create_private_file(path: str | Path) -> None:
    """Create ``path`` empty and ``0600`` if absent (before a library opens it)."""
    target = Path(path)
    ensure_private_dir(target.parent)
    flags = os.O_WRONLY | os.O_CREAT | _NOFOLLOW
    os.close(os.open(target, flags, PRIVATE_FILE_MODE))


def open_lock_file(path: str | Path) -> int:
    """Open, creating it if needed, a lock file owner-only; return the fd.

    A lock holds no data, but its presence and timestamps tell another user
    when Cortex runs. Created ``0600`` with ``O_NOFOLLOW``; a lock an older
    version left with wider bits is tightened through the descriptor. The
    one opener for every lock file (review of PR #775, N6)."""
    flags = os.O_RDWR | os.O_CREAT | _NOFOLLOW
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    if sys.platform == "win32":
        return fd
    try:
        if stat.S_IMODE(os.fstat(fd).st_mode) != PRIVATE_FILE_MODE:
            os.fchmod(fd, PRIVATE_FILE_MODE)
    except OSError:
        os.close(fd)
        raise
    return fd


def _wanted_mode(info: os.stat_result) -> int:
    if stat.S_ISDIR(info.st_mode):
        return PRIVATE_DIR_MODE
    return stat.S_IMODE(info.st_mode) & 0o700


def _tighten(
    name: str | Path,
    info: os.stat_result,
    dir_fd: int | None = None,
    shown: str | Path | None = None,
) -> bool:
    """Make one directory or regular file owner-only, never through a link.

    ``info`` is the entry's ``lstat``. The entry is opened ``O_NOFOLLOW``
    (a symbolic link fails to open), checked to be the same inode, and
    changed with ``fchmod`` on that descriptor. ``shown`` names the entry
    in an error when ``name`` is relative to ``dir_fd``."""
    wanted = _wanted_mode(info)
    if stat.S_IMODE(info.st_mode) == wanted:
        return False
    flags = os.O_RDONLY | _NOFOLLOW | _NONBLOCK
    if stat.S_ISDIR(info.st_mode):
        flags |= _DIRECTORY
    fd = os.open(name, flags, dir_fd=dir_fd)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise OSError(errno.EAGAIN, "replaced while being tightened")
        os.fchmod(fd, wanted)
    except OSError as exc:
        exc.filename = exc.filename or str(shown or name)
        raise
    finally:
        os.close(fd)
    return True


def tighten_tree(root: Path) -> int:
    """Strip group/other bits from every directory and regular file under
    ``root``; return the count. Symbolic links are neither followed nor
    changed, ``root`` included: a root that is a link is not walked."""
    if not stat.S_ISDIR(os.lstat(root).st_mode):
        return 0
    changed = 0
    for path, _dirs, names, dir_fd in os.fwalk(root, follow_symlinks=False):
        changed += _tighten(".", os.fstat(dir_fd), dir_fd, path)
        for name in names:
            info = os.lstat(name, dir_fd=dir_fd)
            if stat.S_ISREG(info.st_mode):
                changed += _tighten(name, info, dir_fd, Path(path, name))
    return changed


Runner = Callable[[Sequence[str]], object]


def restrict_windows_acl(path: Path, run: Runner | None = None) -> None:
    """Grant only the current user full control, inherited by the tree.

    Inheritance is removed in the same call, so an empty principal would
    leave the tree with no usable grant: an empty ``USERNAME`` is refused
    before icacls runs (review of PR #775, N5)."""
    user = os.environ.get("USERNAME", "").strip()
    domain = os.environ.get("USERDOMAIN", "").strip()
    if not user:
        raise OSError(errno.EINVAL, "USERNAME is empty; no ACL principal", str(path))
    principal = f"{domain}\\{user}" if domain else user
    command = [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{principal}:(OI)(CI)F",
    ]
    if run is None:
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603 — fixed system tool
    else:
        run(command)


def _real_dirs(paths: Sequence[Path]) -> list[Path]:
    """The paths that exist as directories, not as links to one."""
    real = []
    for path in paths:
        try:
            if stat.S_ISDIR(os.lstat(path).st_mode):
                real.append(path)
        except FileNotFoundError:
            continue
    return real


def symlinked_roots() -> list[Path]:
    """Private roots that are symbolic links; hardening leaves them alone."""
    return [r for r in private_roots() if r.is_symlink()]


def harden_private_storage(
    *, platform: str = sys.platform, run: Runner | None = None
) -> int:
    """Make every existing private root owner-only; return entries changed.

    The roots are tightened on every call (cheap); their content once per
    install, recorded by a stamp in the methodology directory. A root or a
    file that is a symbolic link is skipped (see the module docstring)."""
    roots = _real_dirs(private_roots())
    if platform == "win32":
        for root in roots:
            restrict_windows_acl(root, run)
        return len(roots)
    changed = 0
    for root in roots:
        changed += _tighten(root, os.lstat(root))
    for file in private_files():
        if file.exists() and stat.S_ISREG(os.lstat(file).st_mode):
            changed += _tighten(file, os.lstat(file))
    stamp = private_roots()[0] / _STAMP_NAME
    if roots and not stamp.exists():
        changed += sum(tighten_tree(root) for root in roots)
        create_private_file(stamp)
    return changed


def harden_at_startup() -> None:
    """Entry-point form: a path that cannot be tightened (another owner, a
    read-only mount) is reported on stderr with its cause; startup goes on."""
    for root in symlinked_roots():
        print(
            f"[cortex] {root} is a symbolic link; its modes are left as they "
            "are (a link is never followed to change permissions)",
            file=sys.stderr,
        )
    try:
        harden_private_storage()
    except OSError as exc:
        print(
            f"[cortex] could not make personal data owner-only: {exc} "
            f"(path: {exc.filename})",
            file=sys.stderr,
        )
