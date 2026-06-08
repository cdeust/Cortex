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


def _contained_resolved(p: "str | Path") -> "Path | None":  # noqa: F821
    """Resolve ``p`` and return it ONLY if it lands inside an allowed probe
    root; otherwise ``None``.

    Sanitise-and-return: the returned Path is the *validated* value, and
    callers must use it (never the raw input) for any subsequent filesystem
    op. This places the ``is_relative_to`` barrier (the canonical CWE-22
    path-traversal sanitiser) directly on the tainted→sink dataflow, which
    CodeQL recognises — so ``?name=`` / ``?path=`` query data can never
    reach a filesystem op that escapes ``$HOME`` / cwd / temp.
    """
    from pathlib import Path

    try:
        target = Path(p).resolve(strict=False)
    except (OSError, ValueError):
        return None
    for root in _allowed_probe_roots():
        try:
            base = Path(root).resolve(strict=False)
        except (OSError, ValueError):
            continue
        if target == base or target.is_relative_to(base):
            return target
    return None


def _under_allowed_root(p: "Path") -> bool:  # noqa: F821
    """Back-compat boolean wrapper around :func:`_contained_resolved`."""
    return _contained_resolved(p) is not None


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
      * ``os.path.normpath`` collapses ``..`` and ``//`` segments.
      * Require absolute paths — relative inputs go straight to CWD.
      * ``_under_allowed_root`` constrains the probe surface to the
        user's ``$HOME``, server CWD, and system temp directories —
        attackers cannot probe ``/etc``, ``/root``, etc.
      * Ancestor walk capped at 64 levels.
      * Only ``is_dir()`` / ``git rev-parse`` run against the
        ancestry — no file content is read in this function.
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

    # Absolute inputs are the COMMON case, not an attack: graph file
    # nodes carry the absolute ``file_path`` captured from the original
    # tool call, on this same machine. The server is loopback-only and
    # ``name`` comes from the user's own stored data, so we resolve the
    # repo from the file's own location — constrained to
    # ``_under_allowed_root`` (HOME / cwd / temp) so a crafted ``?name=``
    # still can't probe ``/etc`` / ``/root`` (CWE-22).
    if clean.startswith(("/", "\\")):
        # Sanitise-and-return: ``target`` is the validated resolved path
        # (gated by is_relative_to), so the value reaching ``is_dir()`` /
        # ``git rev-parse`` below carries the CWE-22 barrier inline.
        target = _contained_resolved(clean)
        if target is None:
            return find_git_root()
        # Walk up to the first directory that exists (handles a file, or
        # an intermediate dir, deleted after capture). Capped at 64.
        start = target
        for _ in range(64):
            if start.is_dir():
                break
            parent = start.parent
            if parent == start:
                break
            start = parent
        root = find_git_root(start)
        return root if root is not None else find_git_root()

    # Relative inputs: join under each allowed probe root and let git
    # walk the ancestry. ``is_relative_to`` keeps the join inside base.
    for base_root in _allowed_probe_roots():
        try:
            base = Path(base_root).resolve(strict=False)
            target = (base / Path(*parts)).resolve(strict=False)
        except (OSError, ValueError):
            continue
        # Canonical CodeQL-recognised sanitiser.
        if not (target == base or target.is_relative_to(base)):
            continue
        try:
            start = target if target.is_dir() else target.parent
        except OSError:
            continue
        if not (start == base or start.is_relative_to(base)):
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
