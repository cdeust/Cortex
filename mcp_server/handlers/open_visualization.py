"""Handler for the open_visualization tool — launches unified 3D graph in browser.

Before spawning the HTTP server this handler syncs the current Cortex
dev checkout onto the plugin's on-disk package path. That means every
``cortex-visualize`` call automatically picks up working-tree changes
— no manual rsync, no env-var configuration, no plugin reinstall. The
sync is idempotent (rsync with ``--delete``) and only runs when a dev
source is visible, so production plugin installs are unaffected.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from mcp_server.server.http_launcher import launch_server, open_in_browser
from mcp_server.handlers._tool_meta import READ_ONLY_EXTERNAL

schema = {
    "title": "Open visualization",
    "annotations": READ_ONLY_EXTERNAL,
    "description": (
        "Open the bundled Cortex visualization in the user's default "
        "browser — a force-directed neural graph combining methodology "
        "profiles, memory nodes, and the knowledge graph, plus the Wiki, "
        "Atlas, Emotion, Board, Pipeline, and Knowledge views. Starts "
        "the local HTTP server on 127.0.0.1:3458 if not already running "
        "and auto-shuts-down after 10 minutes of idle. Use this for "
        "visual exploration, screenshots, or presenting Cortex state. "
        "Distinct from `get_methodology_graph` (returns JSON for a "
        "CUSTOM client, no browser launched, no auxiliary views) and "
        "`list_domains` (text overview, no graph). Side effects: spawns "
        "an HTTP server process and opens a browser tab. Latency ~200ms "
        "(server warmup + browser launch). Returns {url, message}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Restrict the initial graph view to a single cognitive "
                    "domain. Omit to show the full graph (all domains visible)."
                ),
                "examples": ["cortex", "auth-service"],
            },
        },
    },
}


def _find_dev_source() -> Path | None:
    """Locate a Cortex working-tree checkout on the filesystem.

    Same detection order as ``http_launcher._detect_dev_source`` but
    duplicated here so this handler stays usable even when it's loaded
    from an older plugin-cache snapshot whose launcher lacks the
    auto-detect extension.
    """

    def _is_cortex_root(p: Path) -> bool:
        return (
            p.is_dir()
            and (p / "mcp_server").is_dir()
            and (p / "ui" / "unified-viz.html").is_file()
        )

    candidates: list[Path] = []
    for env in ("CORTEX_DEV_ROOT", "CLAUDE_PROJECT_DIR"):
        v = os.environ.get(env)
        if v:
            candidates.append(Path(v))
    candidates.append(Path.home() / "Documents" / "Developments" / "Cortex")
    for c in candidates:
        if _is_cortex_root(c):
            return c
    return None


def _auto_sync_all_caches(src: Path) -> list[str]:
    """Rsync the dev source onto every known plugin / UV cache root.

    Running here — in the handler itself — means every
    ``cortex-visualize`` invocation self-heals the plugin cache. No
    out-of-band ``rsync`` required. Caches we target:

      * ``~/.claude/plugins/cache/cortex-plugins/cortex/<version>/``
      * ``~/.claude/plugins/marketplaces/cdeust-cortex/``
      * ``~/.claude/plugins/marketplaces/cortex-plugins/``
      * ``~/.cache/uv/archive-v0/*/lib/python*/site-packages/``

    Uses rsync when available; falls back to shutil.copytree otherwise.
    All failures are silent (best-effort) so a single bad target can
    never block the launch.
    """
    rsync = shutil.which("rsync")
    roots: list[Path] = []
    home = Path.home()

    # Plugin cache (version-agnostic — pick up every installed).
    for root in (
        home / ".claude" / "plugins" / "cache" / "cortex-plugins" / "cortex"
    ).glob("*"):
        if root.is_dir():
            roots.append(root)
    # Marketplaces.
    for name in ("cdeust-cortex", "cortex-plugins"):
        p = home / ".claude" / "plugins" / "marketplaces" / name
        if p.is_dir():
            roots.append(p)
    # UV archive copies — one per installed wheel identity.
    for arch in (home / ".cache" / "uv" / "archive-v0").glob(
        "*/lib/python*/site-packages"
    ):
        if arch.is_dir():
            roots.append(arch)

    synced: list[str] = []
    for dst in roots:
        for sub in ("mcp_server", "ui"):
            src_sub = src / sub
            dst_sub = dst / sub
            if not src_sub.is_dir():
                continue
            try:
                if rsync:
                    subprocess.run(
                        [rsync, "-a", "--delete", f"{src_sub}/", f"{dst_sub}/"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    if dst_sub.exists():
                        shutil.rmtree(dst_sub, ignore_errors=True)
                    shutil.copytree(src_sub, dst_sub, symlinks=True)
            except Exception:
                continue
        synced.append(str(dst))
    return synced


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


async def handler(args: dict | None = None) -> dict:
    # Python caches every imported module in ``sys.modules``; the
    # long-lived MCP plugin process therefore ignores on-disk edits
    # to handlers/http_launcher. To bypass that, we spawn a short
    # helper script that is always re-parsed from disk — it does
    # detection, rsync, kill-port, and respawn, then exits. Every
    # ``cortex-visualize`` call runs the latest code that way, even
    # without restarting Claude Code.
    dev_src = _find_dev_source()
    bootstrap_path: Path | None = None
    bootstrap_status = "no_dev_source"
    if dev_src is not None:
        bootstrap_path = dev_src / "mcp_server" / "server" / "visualize_bootstrap.py"
        if bootstrap_path.is_file():
            try:
                env = {**os.environ}
                env.setdefault("PYTHONPATH", str(dev_src))
                proc = subprocess.run(
                    [sys.executable, str(bootstrap_path)],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=30,
                )
                bootstrap_status = (proc.stdout or "").strip() or (
                    proc.stderr or ""
                ).strip()
            except Exception as exc:
                bootstrap_status = f"bootstrap_failed: {type(exc).__name__}: {exc}"
        else:
            # Fallback: legacy in-process path when the bootstrap
            # script isn't on disk yet (first run after an older
            # snapshot).
            _auto_sync_all_caches(dev_src)
            _kill_port(3458)

    # Regardless of how we got here, launch + open the browser.
    url = launch_server("unified")
    open_in_browser(url)

    return {
        "url": url,
        "message": f"Unified neural graph opened at {url}",
        "dev_source": str(dev_src) if dev_src else None,
        "bootstrap": bootstrap_status,
    }
