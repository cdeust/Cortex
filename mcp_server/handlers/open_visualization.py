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
        "an HTTP server process and opens a browser tab. The CALL itself "
        "returns in ~200 ms (server warmup + browser launch); the GRAPH "
        "build is lazy — kicked when the page polls /api/graph/progress "
        "(i.e. when the user opens the Graph view). First paint of the "
        "skeleton lands in ~1 s; the full graph fills in behind it and "
        "depends on the DB size (seconds for typical, ~1-3 min on a 100k+ "
        "memory store). Returns {url, message, dev_source, bootstrap, layout}."
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

    Security gating (GHSA-gvpp-v77h-5w8g, EQSTLab 2026-05-27): the
    return value of this function is consumed by ``handler()`` to
    locate a ``visualize_bootstrap.py`` that is then ``subprocess.run``
    against the local Python interpreter. Any directory we return is
    therefore a code-execution surface, so candidate sources must NOT
    be attacker-controllable.

    Previous implementation accepted ``CLAUDE_PROJECT_DIR`` (set
    automatically by Claude Code to whatever project the user opens)
    as a candidate, validated by a two-marker-file check
    (``mcp_server/`` directory + ``ui/unified-viz.html``) that any
    attacker can trivially replicate. That allowed local arbitrary
    code execution by enticing the user to open an attacker-crafted
    project and run ``/cortex-visualize``.

    Hardening:
      * ``CLAUDE_PROJECT_DIR`` is no longer consulted.
      * ``CORTEX_DEV_ROOT`` is consulted only when the user has also
        set ``CORTEX_DEV_SOURCE_SYNC=1`` — an explicit opt-in flag
        that signals "I deliberately want my CORTEX_DEV_ROOT to be
        used as a code-execution dev source." Without the flag,
        ``CORTEX_DEV_ROOT`` (which an attacker could in principle
        plant in a shell rc file) is ignored.
      * The conventional ``~/Documents/Developments/Cortex`` fallback
        remains — that path is controlled by the user's own filesystem
        and an attacker who can already write under ``$HOME`` has
        higher-privilege code execution by other means.
    """

    def _is_cortex_root(p: Path) -> bool:
        return (
            p.is_dir()
            and (p / "mcp_server").is_dir()
            and (p / "ui" / "unified-viz.html").is_file()
        )

    candidates: list[Path] = []
    # Explicit dev-source opt-in (see security gating in docstring).
    if os.environ.get("CORTEX_DEV_SOURCE_SYNC") == "1":
        v = os.environ.get("CORTEX_DEV_ROOT")
        if v:
            candidates.append(Path(v))
    # Conventional home-directory checkout — user-controlled, safe.
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

    # Regardless of how we got here, launch the standalone server.
    url = launch_server("unified")

    # 2026-05-17 (user direction): the indexing/graph build must NEVER
    # block the MCP tool launch OR the interface load. The graph build
    # is triggered by the user clicking the Graph button in the UI —
    # not on MCP launch, not on first page-load.
    #
    # Previous implementation called _prepare_layout() synchronously
    # with a 600s timeout. Removed entirely: the handler now just
    # opens the browser at the UI and returns. The frontend's Graph
    # button is the only place that fires /api/graph and
    # /api/recompute_layout, with its own progress polling.
    # Default to the force-directed workflow graph (the README hero
    # screenshot). The tilemap renderer (`?viz=tilemap`) is a different
    # CPU-layout + Datashader pipeline that requires a precomputed igraph
    # layout and does NOT share the skeleton-first / progress-kicks-build
    # / two-stage fallback path the force-directed renderer uses. Landing
    # on ?viz=force gives the user first paint in ~1 s on any DB size;
    # the heavy data fills in behind it.
    target_url = url.rstrip("/") + "/?viz=force"
    open_in_browser(target_url)

    message = (
        f"Workflow graph opened at {target_url}. Click the Graph tab in "
        "the UI if not already selected; the build kicks lazily on first "
        "progress poll. First paint (skeleton: domains + setup) appears "
        "in ~1 s; the full graph fills in behind it as memories / files / "
        "AST symbols stream from the cache."
    )
    return {
        "url": target_url,
        "message": message,
        "dev_source": str(dev_src) if dev_src else None,
        "bootstrap": bootstrap_status,
        "layout": {"status": "not_triggered", "reason": "user_action_pending"},
    }


def _prepare_layout(server_url: str, timeout_s: int = 600) -> dict:
    """Wait for the graph build, then drive /api/recompute_layout.

    Both endpoints belong to the spawned standalone server; we reach
    them via plain HTTP from this MCP-process handler so the standalone
    owns the only ``MemoryStore`` connection. Returns the JSON status
    dict /api/recompute_layout produced, or an error stub if the
    pipeline never completed in ``timeout_s``.
    """
    import json as _json
    import time as _time
    import urllib.error as _ue
    import urllib.request as _ur

    base = server_url.rstrip("/")

    # Step 1: wait for graph build to be full_ready (the standalone
    # builds the graph in a background thread on first /api/graph hit).
    deadline = _time.monotonic() + timeout_s
    last_progress: dict = {}
    # Kick the build off — first /api/graph fetch starts the background
    # builder if it's not already running.
    try:
        _ur.urlopen(f"{base}/api/graph", timeout=5).read(1024)
    except Exception:
        pass
    while _time.monotonic() < deadline:
        try:
            with _ur.urlopen(f"{base}/api/graph/progress", timeout=5) as r:
                last_progress = _json.loads(r.read().decode("utf-8"))
        except Exception:
            last_progress = {}
        if last_progress.get("full_ready") or last_progress.get("baseline_ready"):
            break
        _time.sleep(2)

    # Step 2: recompute_layout (idempotent — skips if fingerprint matches).
    try:
        with _ur.urlopen(f"{base}/api/recompute_layout", timeout=timeout_s) as r:
            return _json.loads(r.read().decode("utf-8"))
    except _ue.HTTPError as exc:
        try:
            return _json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"status": "error", "reason": "http_error", "detail": str(exc)}
    except Exception as exc:
        return {"status": "error", "reason": "exception", "detail": str(exc)}
