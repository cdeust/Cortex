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


def _descend_trusted(root: str, names: "list[str]") -> "Path | None":  # noqa: F821
    """Descend from a TRUSTED ``root`` into child directories whose names
    match the successive user-supplied ``names``, returning the deepest
    existing directory reached.

    CWE-22 taint break: this is the ``git_diff._match_in_whitelist`` pattern
    applied to directory traversal. At every level the candidate paths come
    from ``os.scandir(cur)`` — a trusted enumeration of what is actually on
    disk — and a user component selects among them ONLY via ``entry.name ==
    name`` equality. The path that reaches the ``is_dir`` / ``scandir`` sink
    (``cur`` / ``entry.path``) is composed entirely from the constant
    ``root`` plus scandir output; the user ``names`` never construct a probed
    path. Static analysers (CodeQL ``py/path-injection``) therefore see the
    sink operand as not derived from user input. Capped at 64 levels.
    """
    import os
    from pathlib import Path

    cur = os.path.realpath(root)  # ``root`` is a constant probe root → trusted
    if not os.path.isdir(cur):
        return None
    deepest = cur
    for name in names[:64]:
        nxt = None
        try:
            with os.scandir(cur) as entries:
                for entry in entries:
                    # Equality match only — ``name`` selects a trusted entry,
                    # it never builds the path that gets probed.
                    if entry.name == name and entry.is_dir():
                        nxt = entry.path
                        break
        except (OSError, ValueError):
            break
        if nxt is None:
            break
        cur = nxt
        deepest = cur
    return Path(deepest)


def _first_existing_dir_within(target: "Path") -> "Path | None":  # noqa: F821
    """Deepest existing directory on ``target``'s path chain, found by
    DESCENDING from the allowed probe root that contains it — never by
    probing a ``realpath(user_input)``-derived path.

    CWE-22 taint break (redesign): the up-walk variant fed ``is_dir()`` a
    value derived from the user-controlled ``target`` on every iteration,
    which CodeQL's loop-carried dataflow re-taints and refuses to treat as
    sanitised. Instead we locate the constant allowed root that prefixes
    ``target`` (a pure segment comparison — no filesystem op on user data),
    then hand the remaining components to :func:`_descend_trusted`, where the
    filesystem sinks only ever touch trusted enumerated paths. ``target`` is
    used solely to *choose* a root and *compare* component names.
    """
    import os

    real = os.path.realpath(str(target))
    target_parts = [p for p in real.split(os.sep) if p]
    for root in _allowed_probe_roots():
        root_parts = [p for p in root.split(os.sep) if p]
        if target_parts[: len(root_parts)] != root_parts:
            continue
        return _descend_trusted(root, target_parts[len(root_parts) :])
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
      * ``_contained_resolved`` bounds the input to ``$HOME`` / cwd / temp
        (``os.path.commonpath``), so anything outside falls back to CWD.
      * The directory actually probed is reached by DESCENDING from a
        constant allowed root via ``_first_existing_dir_within`` /
        ``_descend_trusted`` (``os.scandir``): the value that reaches
        ``is_dir`` / ``git rev-parse --cwd`` is composed from trusted
        enumeration, not from ``name`` — the CWE-22 taint flow is broken
        the same way ``git_diff._match_in_whitelist`` breaks it.
      * Descent capped at 64 levels.
      * Only directory probes / ``git rev-parse`` run against the path —
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
    # HOME / cwd / temp, then ``_first_existing_dir_within`` DESCENDS from the
    # containing trusted root via ``os.scandir`` to the deepest existing dir —
    # so the path reaching the git sink is trusted enumeration (CWE-22).
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
