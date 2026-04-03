"""Launch standalone HTTP servers as detached processes.

Spawns http_standalone.py as an independent process that survives MCP
server shutdown. Reuses an existing server if one is already listening
on the expected port.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# Port assignments — one per server type
PORTS = {
    "methodology": 3456,
    "unified": 3458,
}


def _probe_port(port: int) -> str | None:
    """Check if a server is already listening. Returns URL or None."""
    url = f"http://127.0.0.1:{port}"
    try:
        resp = urllib.request.urlopen(url, timeout=1)
        resp.read()
        return url
    except Exception:
        return None


def launch_server(server_type: str) -> str:
    """Launch a standalone server, reusing if already running. Returns URL.

    Args:
        server_type: One of 'dashboard', 'unified', 'methodology'.

    Returns:
        The URL where the server is listening.
    """
    port = PORTS[server_type]

    # Reuse existing server if alive
    existing = _probe_port(port)
    if existing:
        return existing

    # Find the standalone module
    standalone = Path(__file__).parent / "http_standalone.py"

    # Build env — inherit everything, ensure PYTHONPATH and DATABASE_URL
    env = {**os.environ}
    pkg_root = str(Path(__file__).parent.parent.parent)
    existing_pp = env.get("PYTHONPATH", "")
    if pkg_root not in existing_pp:
        env["PYTHONPATH"] = f"{pkg_root}:{existing_pp}" if existing_pp else pkg_root

    # Ensure DATABASE_URL is set for the subprocess
    if not env.get("DATABASE_URL"):
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        env["DATABASE_URL"] = settings.DATABASE_URL or "postgresql://localhost:5432/cortex"

    # Spawn detached process
    proc = subprocess.Popen(
        [sys.executable, str(standalone), "--type", server_type, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,  # detach from parent process group
    )

    # Read the URL from stdout (the child writes it then closes stdout)
    try:
        raw = proc.stdout.readline()
        proc.stdout.close()
        info = json.loads(raw)
        return info["url"]
    except Exception as e:
        # If we can't read the URL, try the expected port
        fallback = _probe_port(port)
        if fallback:
            return fallback
        raise RuntimeError(
            f"Failed to start standalone {server_type} server: {e}"
        ) from e


def open_in_browser(url: str) -> None:
    """Open a URL in the default browser (cross-platform)."""
    try:
        subprocess.Popen(
            ["open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        try:
            subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # No browser opener available
