"""Shared HTTP plumbing for the marketplace pin-staleness gate.

Split out of check_marketplace_pins.py (issue: that file crossed the
300-line §4.1 cap once REGISTRY_VERSION_STALE was added) — every module
that talks to a JSON API (GitHub REST, the public MCP registry) shares
this request-header builder, timeout, and the one HTTP status code they
all treat specially.
"""

from __future__ import annotations

import os

API_TIMEOUT_S = 15  # source: GitHub API p99 well below; matches prior gate rev

# source: RFC 9110 §15.5.5 — HTTP 404 Not Found
HTTP_NOT_FOUND = 404


def api_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "pin-gate"}
    if token := os.environ.get("GITHUB_TOKEN", ""):
        headers["Authorization"] = f"Bearer {token}"
    return headers
