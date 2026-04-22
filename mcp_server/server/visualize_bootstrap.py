"""Fresh-from-disk bootstrap for ``cortex-visualize``.

The MCP plugin runs as a long-lived Python process: once it imports
``handlers/open_visualization`` and ``server/http_launcher`` there is no
cheap way to pick up new code on disk without reloading the whole
module tree. That meant every ``cortex-visualize`` call in a long
session kept firing the handler snapshot the plugin had loaded on
startup — auto-sync and live-stream fixes stayed invisible until the
user restarted Claude Code.

This file is the fix: a minimal script that is always re-parsed from
disk when the handler ``subprocess.Popen``s it. It takes care of:

  1. Locating the Cortex dev checkout (same detection the handler uses).
  2. Rsyncing the dev source onto every known plugin / UV cache root.
  3. Killing any stale HTTP server on port 3458.
  4. Spawning ``http_standalone.py --type unified --port 3458`` from
     the just-synced package path.

Because step 4 is a separate Python process that imports from the
freshly-synced cache, it always runs the current code. The long-lived
MCP plugin process just invokes this helper via subprocess and returns
the URL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PORT = 3458


def _is_cortex_root(p: Path) -> bool:
    return (
        p.is_dir()
        and (p / "mcp_server").is_dir()
        and (p / "ui" / "unified-viz.html").is_file()
    )


def _find_dev_source() -> Path | None:
    for env in ("CORTEX_DEV_ROOT", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(env)
        if v and _is_cortex_root(Path(v)):
            return Path(v)
    default = Path.home() / "Documents" / "Developments" / "Cortex"
    if _is_cortex_root(default):
        return default
    return None


def _cache_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    for d in (
        home / ".claude" / "plugins" / "cache" / "cortex-plugins" / "cortex"
    ).glob("*"):
        if d.is_dir():
            roots.append(d)
    for name in ("cdeust-cortex", "cortex-plugins"):
        p = home / ".claude" / "plugins" / "marketplaces" / name
        if p.is_dir():
            roots.append(p)
    # EVERY uv archive that contains an ``mcp_server`` package — uv
    # hashes env + wheel-set so different plugin versions end up in
    # different archive roots. If we only rsync one, whichever archive
    # happens to be the resolved plugin env at launch runs stale code.
    for arch in (home / ".cache" / "uv" / "archive-v0").glob(
        "*/lib/python*/site-packages"
    ):
        if (arch / "mcp_server").is_dir():
            roots.append(arch)
    return roots


def _sync(src: Path) -> int:
    rsync = shutil.which("rsync")
    count = 0
    for dst in _cache_roots():
        for sub in ("mcp_server", "ui"):
            s = src / sub
            d = dst / sub
            if not s.is_dir():
                continue
            try:
                if rsync:
                    subprocess.run(
                        [rsync, "-a", "--delete", f"{s}/", f"{d}/"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    if d.exists():
                        shutil.rmtree(d, ignore_errors=True)
                    shutil.copytree(s, d, symlinks=True)
            except Exception:
                continue
        count += 1
    return count


def _kill_port(port: int) -> None:
    try:
        out = (
            subprocess.check_output(
                ["lsof", "-t", "-i", f":{port}"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return
    for pid_s in out.splitlines():
        try:
            pid = int(pid_s.strip())
            os.kill(pid, 15)
        except Exception:
            pass


def _spawn_server(src: Path) -> None:
    """Spawn ``http_standalone.py`` from the freshly-synced source so
    the new server process always runs the latest code."""
    standalone = src / "mcp_server" / "server" / "http_standalone.py"
    if not standalone.is_file():
        return
    env = {**os.environ}
    existing = env.get("PYTHONPATH", "")
    pkg_root = str(src)
    if pkg_root not in existing:
        env["PYTHONPATH"] = f"{pkg_root}:{existing}" if existing else pkg_root
    subprocess.Popen(
        [
            sys.executable,
            str(standalone),
            "--type",
            "unified",
            "--port",
            str(PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )


def main() -> None:
    src = _find_dev_source()
    if src is None:
        print("no_dev_source", flush=True)
        return
    synced = _sync(src)
    _kill_port(PORT)
    _spawn_server(src)
    print(f"ok synced={synced} url=http://127.0.0.1:{PORT}", flush=True)


if __name__ == "__main__":
    main()
