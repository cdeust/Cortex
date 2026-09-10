"""Shared HTTP plumbing for the marketplace pin-staleness gate.

source: ADR-0754"""

from __future__ import annotations

import os

API_TIMEOUT_S = 15  # source: ADR-0754

# source: ADR-0754
HTTP_NOT_FOUND = 404


def api_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "pin-gate"}
    if token := os.environ.get("GITHUB_TOKEN", ""):
        headers["Authorization"] = f"Bearer {token}"
    return headers
