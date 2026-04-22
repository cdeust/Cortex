"""Response helpers for the standalone HTTP server.

Every wiki / graph / discussion endpoint repeats the same 6-line
boilerplate: ``send_response(200)`` → set ``Content-Type`` → apply CORS
headers → set ``Cache-Control`` → ``end_headers`` → write body, plus a
matching 500-branch that prints the traceback to stderr and writes a
sanitized error name. Centralising the two patterns here keeps
``http_standalone.py`` under the 300-line ceiling without changing any
observable HTTP behaviour.
"""

from __future__ import annotations

import json
import sys
import traceback

from mcp_server.server.http_common import _apply_cors_headers


def send_json_ok(handler, data: dict | list, cache_control: str = "no-cache") -> None:
    """Send a 200 JSON response with loopback-strict CORS.

    ``Content-Length`` is mandatory here. ``BaseHTTPRequestHandler``
    runs at ``HTTP/1.1`` with keep-alive; without an explicit framing
    header (``Content-Length`` or chunked encoding) the browser reads
    until the connection closes and every ``fetch()`` hangs for the
    ~60 s keep-alive idle — manifesting as an infinite loading spinner
    even though the server already wrote the body. Setting the length
    lets the client parse the response and free the socket.
    """
    body = json.dumps(data, default=str).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    _apply_cors_headers(handler)
    if cache_control:
        handler.send_header("Cache-Control", cache_control)
    handler.end_headers()
    handler.wfile.write(body)


def send_json_error(handler, exc: BaseException, status: int = 500) -> None:
    """Send a JSON error response with the exception class name.

    The body never echoes ``str(exc)`` because user-controlled data can
    reach that surface (file paths, query strings); we log the full
    traceback to stderr instead.
    """
    body = json.dumps({"error": type(exc).__name__}).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    traceback.print_exc(file=sys.stderr)
    handler.wfile.write(body)


def send_plain_error(handler, status: int) -> None:
    """Send a bare status response with no body."""
    handler.send_response(status)
    handler.end_headers()
