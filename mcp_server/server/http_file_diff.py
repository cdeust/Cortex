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
        handler.send_response(400)
        handler.end_headers()
        return

    from pathlib import Path

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


def _git_root_for_name(name: str, find_git_root) -> "Path | None":  # noqa: F821
    """Resolve git root from the file's own path, then fall back to CWD.

    Handles the case where the file (and intermediate directories) have
    been deleted — walks UP the path until a parent exists on disk,
    then runs ``git rev-parse --show-toplevel`` from there. If nothing
    along the ancestry exists, falls back to the server's cwd repo so
    that a tracked-then-deleted file can still be recovered from history.
    """
    from pathlib import Path

    try:
        p = Path(name.strip().strip("\"'`"))
    except (ValueError, OSError):
        return find_git_root()

    if p.is_absolute():
        # Walk up the ancestry until we hit an existing directory.
        cursor = p.parent
        while cursor != cursor.parent:
            if cursor.exists() and cursor.is_dir():
                root = find_git_root(cursor)
                if root is not None:
                    return root
                break
            cursor = cursor.parent
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
    """Send a JSON response with CORS headers."""
    body = json.dumps(data, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    # Strict-reflect CORS against the loopback allowlist (CWE-942). The
    # previous ``http://127.0.0.1`` string didn't match any browser's
    # Origin header (which always carries a port), so no origin ever
    # passed — this is both a correctness and a hardening fix.
    _apply_cors_headers(handler)
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
