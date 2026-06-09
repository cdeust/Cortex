"""HTTP handler for file diff API endpoint.

Serves git diff data for file entities in the visualization.
Resolves file paths (absolute, relative, or bare names) to
repo-relative paths, then returns structured diff lines.

Server layer - routes HTTP requests to infrastructure.

Security: CORS uses strict-reflect via ``_apply_cors_headers`` so only
loopback origins can read the diff payload (CWE-942). The caller is
expected to have already run ``validate_host_header`` on the incoming
request — this module only formats responses.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

from mcp_server.server.http_common import _apply_cors_headers


def serve_file_diff(handler) -> None:
    """Handle GET /api/file-diff?name=<filename>.

    Memories often carry absolute paths from repos OTHER than the server's
    CWD. We derive git_root from the file's path (walk up its parents) so
    cross-repo diffs work, then fall back to the server CWD's repo.
    """
    name = _extract_name_param(handler.path)
    if not name:
        _json_response(handler, {"error": "missing 'name' parameter"}, 400)
        return

    from mcp_server.infrastructure.git_diff import (
        find_git_root,
        get_file_diff,
        resolve_file,
    )

    git_root = _git_root_for_name(name, find_git_root)
    if not git_root:
        _json_response(handler, {"error": "not a git repo", "file": name}, 404)
        return

    # Normalize to repo-relative if possible, then ALWAYS hand to
    # ``get_file_diff`` — that function handles tracked / untracked /
    # deleted / new-file / clean-tracked uniformly and never returns
    # empty lines unless the file genuinely doesn't exist anywhere.
    resolved = resolve_file(name, git_root) or _to_repo_rel(name, git_root)
    data = get_file_diff(resolved, git_root)
    _json_response(handler, data)


def _to_repo_rel(name: str, git_root) -> str:
    """Best-effort repo-relative path — strip quotes; make relative if
    absolute and inside git_root; otherwise pass through."""
    from pathlib import Path

    clean = name.strip().strip("\"'`")
    try:
        p = Path(clean)
        if p.is_absolute():
            try:
                return str(p.relative_to(git_root))
            except ValueError:
                return clean
    except (ValueError, OSError):
        pass
    return clean


def _allowed_probe_roots() -> "list[str]":
    """Real-path roots under which ancestor-walking probes are allowed.

    CWE-22 containment: we only probe directories that the user could
    legitimately own (home, temp, current workdir). Anything outside
    falls back to the server's CWD git root. This gives CodeQL an
    explicit boundary on ``name``-derived path operations without
    breaking the "repo on this laptop" use-case.
    """
    import os
    from pathlib import Path

    roots: list[str] = []
    for candidate in (str(Path.home()), os.getcwd(), "/tmp", "/var/folders"):
        try:
            roots.append(os.path.realpath(candidate))
        except (OSError, ValueError):
            continue
    return roots


def _within(real_path: str, root: str) -> bool:
    """True iff ``real_path`` is ``root`` or nested beneath it.

    ``os.path.commonpath`` is the canonical CWE-22 containment barrier and
    is recognised by CodeQL's path-injection dataflow as a sanitising guard.
    It compares whole path *segments*, so ``/home/user`` does not "contain"
    ``/home/user-evil`` the way a naive ``startswith`` prefix test would.
    Both inputs are expected to be real-paths, so symlink escapes are already
    collapsed before the comparison.
    """
    import os

    try:
        return os.path.commonpath([root, real_path]) == root
    except (ValueError, OSError):
        # ValueError: paths on different drives or mixed absolute/relative.
        return False


def _contained_resolved(p: "str | Path") -> "Path | None":  # noqa: F821
    """Real-path ``p`` and return it ONLY if it lands inside an allowed probe
    root; otherwise ``None``.

    Sanitise-and-return: callers must use the returned Path (never the raw
    input) for any subsequent filesystem op. ``os.path.realpath`` normalises
    ``..`` and symlink segments, and ``_within`` (``os.path.commonpath``) is
    the CodeQL-recognised barrier placed directly on the tainted→sink
    dataflow — so ``?name=`` / ``?path=`` query data can never reach a
    filesystem op that escapes ``$HOME`` / cwd / temp.
    """
    import os
    from pathlib import Path

    try:
        real = os.path.realpath(str(p))
    except (OSError, ValueError):
        return None
    for root in _allowed_probe_roots():
        if _within(real, root):
            return Path(real)
    return None


def _first_existing_dir_within(target: "Path") -> "Path | None":  # noqa: F821
    """Walk UP from ``target`` to the first directory that exists on disk,
    never leaving an allowed probe root. Capped at 64 levels.

    The ``_within`` guard is re-asserted on every iteration *before* the
    ``is_dir()`` sink, so the CWE-22 containment barrier dominates the
    filesystem access locally even as the walk ascends toward the root —
    a crafted ``?name=`` cannot make the probe climb out to ``/`` or ``/etc``.
    """
    import os
    from pathlib import Path

    roots = _allowed_probe_roots()
    cur = target
    for _ in range(64):
        real = os.path.realpath(str(cur))
        contained = False
        for root in roots:
            try:
                # Inline CWE-22 barrier: the ``is_dir()`` sink lives directly
                # inside the ``commonpath`` guard so it dominates the filesystem
                # access on ``real`` — this is the exact shape CodeQL's
                # path-injection dataflow recognises as a sanitiser (a guard
                # behind a helper / ``any(...)`` generator is NOT recognised).
                if os.path.commonpath([root, real]) == root:
                    contained = True
                    if Path(real).is_dir():
                        return Path(real)
                    break
            except (ValueError, OSError):
                continue
        if not contained:
            return None
        parent = os.path.dirname(real)
        if parent == real:
            return None
        cur = Path(parent)
    return None


def _git_root_for_name(name: str, find_git_root) -> "Path | None":  # noqa: F821
    """Resolve git root from the file's own path, then fall back to CWD.

    Handles the case where the file (and intermediate directories) have
    been deleted — walks UP the path until a parent exists on disk,
    then runs ``git rev-parse --show-toplevel`` from there. If nothing
    along the ancestry exists, falls back to the server's cwd repo so
    that a tracked-then-deleted file can still be recovered from history.

    Security (CWE-22): ``name`` is user-controlled (via ``?name=``
    query parameter). Defences:

      * Strip surrounding quotes, reject empty/null-byte inputs.
      * ``..`` segments are rejected outright — input falls back to CWD.
      * Every probed path is real-pathed and gated by ``_within``
        (``os.path.commonpath``) against ``$HOME`` / cwd / temp, so
        attackers cannot probe ``/etc``, ``/root``, etc.
      * Ancestor walk capped at 64 levels (``_first_existing_dir_within``).
      * Only ``is_dir()`` / ``git rev-parse`` run against the ancestry —
        no file content is read in this function.
    """
    from pathlib import Path

    try:
        clean = name.strip().strip("\"'`")
        if not clean or "\x00" in clean:
            return find_git_root()
        parts = [p for p in clean.replace("\\", "/").split("/") if p and p != "."]
        # ``..`` traversal is never resolved — fall back to the CWD repo.
        if any(p == ".." for p in parts):
            return find_git_root()
    except (ValueError, OSError):
        return find_git_root()

    # Absolute inputs are the COMMON case, not an attack: graph file nodes
    # carry the absolute ``file_path`` captured from the original tool call,
    # on this same machine. ``_contained_resolved`` bounds the path to
    # HOME / cwd / temp, then ``_first_existing_dir_within`` walks up to the
    # first existing dir — both gated by the ``commonpath`` barrier (CWE-22).
    if clean.startswith(("/", "\\")):
        target = _contained_resolved(clean)
        if target is None:
            return find_git_root()
        start = _first_existing_dir_within(target)
        if start is None:
            return find_git_root()
        root = find_git_root(start)
        return root if root is not None else find_git_root()

    # Relative inputs: join under each allowed probe root, contain it, then
    # walk to the first existing dir within that root.
    for base_root in _allowed_probe_roots():
        target = _contained_resolved(str(Path(base_root) / Path(*parts)))
        if target is None:
            continue
        start = _first_existing_dir_within(target)
        if start is None:
            continue
        root = find_git_root(start)
        if root is not None:
            return root
        break
    return find_git_root()


def _extract_name_param(path: str) -> str:
    """Extract the 'name' query parameter from a URL path."""
    if "?" not in path:
        return ""
    for param in path.split("?", 1)[1].split("&"):
        if param.startswith("name="):
            return unquote(param[5:])
    return ""


def _json_response(handler, data: dict, code: int = 200) -> None:
    """Send a JSON response with CORS headers.

    MUST include a ``Content-Length`` header — the server runs HTTP/1.1
    with keep-alive, and without Content-Length the browser's
    ``fetch()`` never resolves (connection stays open waiting for more
    bytes), which leaves the diff modal stuck on "Loading…".
    """
    body = json.dumps(data, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    # Strict-reflect CORS against the loopback allowlist (CWE-942). The
    # previous ``http://127.0.0.1`` string didn't match any browser's
    # Origin header (which always carries a port), so no origin ever
    # passed — this is both a correctness and a hardening fix.
    _apply_cors_headers(handler)
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
