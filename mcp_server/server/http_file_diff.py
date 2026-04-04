"""HTTP handler for file diff API endpoint.

Serves git diff data for file entities in the visualization.
Resolves file paths (absolute, relative, or bare names) to
repo-relative paths, then returns structured diff lines.

Server layer - routes HTTP requests to infrastructure.
"""

from __future__ import annotations

import json
from urllib.parse import unquote


def serve_file_diff(handler) -> None:
    """Handle GET /api/file-diff?name=<filename>."""
    name = _extract_name_param(handler.path)
    if not name:
        handler.send_response(400)
        handler.end_headers()
        return

    from mcp_server.infrastructure.git_diff import (
        find_git_root,
        get_file_diff,
        resolve_file,
    )

    git_root = find_git_root()
    if not git_root:
        _json_response(handler, {"error": "not a git repo"}, 404)
        return

    resolved = resolve_file(name, git_root)
    if not resolved:
        _json_response(handler, _empty_diff(name))
        return

    data = get_file_diff(resolved, git_root)
    _json_response(handler, data)


def _extract_name_param(path: str) -> str:
    """Extract the 'name' query parameter from a URL path."""
    if "?" not in path:
        return ""
    for param in path.split("?", 1)[1].split("&"):
        if param.startswith("name="):
            return unquote(param[5:])
    return ""


def _empty_diff(name: str) -> dict:
    """Return an empty diff response."""
    return {"file": name, "diff_type": "none", "lines": [], "truncated": False}


def _json_response(handler, data: dict, code: int = 200) -> None:
    """Send a JSON response with CORS headers."""
    body = json.dumps(data, default=str).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
