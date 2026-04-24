"""Launch standalone HTTP servers as detached processes.

Spawns http_standalone.py as an independent process that survives MCP
server shutdown. Reuses an existing server if one is already listening
on the expected port.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# Port assignments — one per server type. The ``methodology``
# entry was removed in Gap 10 along with the broken
# ``build_methodology_handler`` it depended on.
PORTS = {
    "unified": 3458,
}


def _kill_port(port: int) -> None:
    """Kill any process listening on ``port``. Best-effort — if ``lsof``
    is unavailable or fails, silently return so we still attempt a spawn."""
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
        except ValueError:
            continue
        try:
            os.kill(pid, 15)
        except Exception:
            pass


def _detect_dev_source() -> Path | None:
    """Return a dev-checkout source root if one is visible.

    Detection order:
      1. ``CORTEX_DEV_ROOT`` env var — explicit override.
      2. ``CLAUDE_PROJECT_DIR`` env var — Claude Code sets this when
         the user is working inside a project directory.
      3. The file the launcher module was loaded from, if it's inside
         a Cortex source tree (auto-detect for dev mode).
      4. The conventional checkout location
         ``$HOME/Documents/Developments/Cortex`` — falls back here so
         the MCP itself syncs on every ``cortex-visualize`` call with
         no env-var configuration.

    A directory qualifies only if it contains both ``mcp_server/`` and
    ``ui/unified-viz.html``. When a dev source is returned
    ``launch_server`` rsyncs it over the package path and restarts the
    HTTP server so the visualization always reflects the current
    working tree.
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
    # Walk up from this module to see if we're loaded out of a source
    # checkout (for ``uv run`` / ``pip install -e`` dev mode).
    here = Path(__file__).resolve()
    for ancestor in list(here.parents)[:6]:
        candidates.append(ancestor)
    # Conventional location — the MCP plugin auto-syncs from here even
    # when no env var is set.
    candidates.append(Path.home() / "Documents" / "Developments" / "Cortex")

    for c in candidates:
        if _is_cortex_root(c):
            return c
    return None


def _find_ap_binary() -> str | None:
    """Locate a built ``ai-architect-mcp`` (automatised-pipeline).

    Checks, in order:
      1. ``CORTEX_AP_COMMAND`` already set — caller knows the path.
      2. A sibling dev checkout: ``~/Documents/Developments/automatised-pipeline/target/release/ai-architect-mcp``.
      3. ``ai-architect-mcp`` on ``PATH``.

    Returns the absolute binary path, or ``None`` if not buildable. We
    do NOT build here — building requires Rust + cmake and can take
    minutes.
    """
    if os.environ.get("CORTEX_AP_COMMAND"):
        return None  # caller explicitly configured it — leave alone
    dev = (
        Path.home()
        / "Documents/Developments/automatised-pipeline/target/release/ai-architect-mcp"
    )
    if dev.is_file() and os.access(dev, os.X_OK):
        return str(dev)
    path_hit = shutil.which("ai-architect-mcp")
    return path_hit


def _ensure_ap_graph(dev_src: Path | None, env: dict) -> None:
    """If AP is available, ensure a graph exists and point env at it.

    AP is on by default via ``MemorySettings.AP_ENABLED``; this function
    only locates the binary + graph path for the spawned server.

    Sets these env vars (which the spawned server reads):
      * ``CORTEX_AP_COMMAND``       — JSON spec the bridge consumes.
      * ``CORTEX_AP_GRAPH_PATH``    — LadybugDB graph dir.

    Indexing uses ``index_codebase`` (Stage 3a) only — fast (~7s on a
    mid-sized tree) and enough for Phase-1 symbol/edge queries. If the
    user needs Phase-3 search they can re-index with
    ``analyze_codebase`` manually (Stage 3d needs clustering).

    Graph cache lives at ``~/.cortex/ap_graph``. We reuse it when
    present so repeated visualize calls don't re-index.
    """
    bin_path = _find_ap_binary()
    if bin_path is None and not os.environ.get("CORTEX_AP_COMMAND"):
        return
    if bin_path and not env.get("CORTEX_AP_COMMAND"):
        env["CORTEX_AP_COMMAND"] = json.dumps(
            {"command": bin_path, "args": []},
        )
    # Graph path. AP writes the LadybugDB as a file named ``graph`` inside
    # ``output_dir``, so ``exists()`` (not ``is_dir()``) is the right check.
    if env.get("CORTEX_AP_GRAPH_PATH") and Path(env["CORTEX_AP_GRAPH_PATH"]).exists():
        return
    cache_dir = Path.home() / ".cortex" / "ap_graph"
    graph_file = cache_dir / "graph"
    if graph_file.exists():
        env["CORTEX_AP_GRAPH_PATH"] = str(graph_file)
        return
    # No graph yet — trigger a one-shot index in the background so the
    # first visualize call returns quickly. The graph will be picked up
    # by the NEXT launch (the user hard-reloads the page).
    target = str(dev_src) if dev_src else str(Path.cwd())
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(  # noqa: S603
            [
                bin_path or "ai-architect-mcp",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # We kick off one MCP call via the bridge directly. It's more
        # reliable than raw stdin piping and reuses the production path.
        import asyncio

        from mcp_server.infrastructure.ap_bridge import APBridge

        async def _index():
            b = APBridge()
            try:
                # analyze_codebase = index + resolve + cluster. Using
                # the composed tool so Calls_* / Imports_* / Extends_*
                # rel tables land populated; index_codebase alone
                # leaves them empty (matched to the viz filter bug).
                await b.analyze_codebase(
                    target,
                    output_dir=str(cache_dir),
                    language="auto",
                )
            finally:
                await b.close()

        # Run in a dedicated thread so we don't block launch. If indexing
        # takes longer than one visualize call, the user sees an empty
        # AST layer on first load and the full one on reload — that's
        # the correct tradeoff for a non-blocking UX.
        import threading

        threading.Thread(
            target=lambda: asyncio.run(_index()),
            name="ap-bg-indexer",
            daemon=True,
        ).start()
        env["CORTEX_AP_GRAPH_PATH"] = str(graph_file)
    except Exception:
        # Best-effort — launch proceeds; APBridge.connect() will fail
        # quietly and the native AST source fills the L6 ring.
        env.pop("CORTEX_AP_COMMAND", None)


def _sync_dev_source(src_root: Path, pkg_root: Path) -> None:
    """Copy ``mcp_server/`` and ``ui/`` from ``src_root`` on top of
    ``pkg_root``. Uses ``rsync`` when available for speed; falls back
    to ``shutil.copytree`` otherwise.

    Idempotent and cheap — only changed files move. This is the
    escape hatch that keeps a stale plugin cache from serving old
    assets when a dev checkout is present.
    """
    rsync = shutil.which("rsync")
    subdirs = ("mcp_server", "ui")
    for sub in subdirs:
        src = src_root / sub
        if not src.is_dir():
            continue
        dst = pkg_root / sub
        try:
            if rsync:
                subprocess.run(
                    [rsync, "-a", "--delete", f"{src}/", f"{dst}/"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst, symlinks=True)
        except Exception:
            # Best-effort — a sync failure should never block launch.
            pass


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
        server_type: Currently only 'unified' is supported; older
            'methodology' type was removed in Gap 10.

    Returns:
        The URL where the server is listening.
    """
    port = PORTS[server_type]

    # Always-fresh policy: if a dev checkout is visible, overlay it
    # onto the package path and kill any running server so the spawn
    # below picks up the current source. Without this the plugin
    # cache would serve yesterday's UI indefinitely.
    pkg_root = Path(__file__).parent.parent.parent
    dev_src = _detect_dev_source()
    if dev_src is not None and dev_src != pkg_root:
        _sync_dev_source(dev_src, pkg_root)
        _kill_port(port)

    # Reuse existing server if alive (and no dev-source sync happened above).
    existing = _probe_port(port)
    if existing:
        return existing

    # Find the standalone module
    standalone = Path(__file__).parent / "http_standalone.py"

    # Build env — inherit everything, ensure PYTHONPATH includes our package
    env = {**os.environ}
    pkg_root_str = str(pkg_root)
    existing_pp = env.get("PYTHONPATH", "")
    if pkg_root_str not in existing_pp:
        env["PYTHONPATH"] = (
            f"{pkg_root_str}:{existing_pp}" if existing_pp else pkg_root_str
        )

    # ADR-0046 — always-on AST enrichment in the served graph. Detects
    # an installed automatised-pipeline binary, sets the feature flag,
    # and launches a background index of the current project so the
    # spawned server reads symbol/edge data on its first /api/graph
    # call. Safe no-op when AP isn't available.
    if server_type == "unified":
        _ensure_ap_graph(dev_src, env)

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
    """Open a URL in the default browser (cross-platform).

    Security: URL is validated to be a localhost HTTP URL before being
    passed to the system browser opener (CWE-78 mitigation). Only
    http://127.0.0.1:* URLs are allowed — no arbitrary command execution.
    """
    import re

    # Strict allowlist: only localhost HTTP URLs on numeric ports
    if not re.match(r"^https?://127\.0\.0\.1:\d{1,5}(/.*)?$", url):
        return  # Silently reject non-localhost URLs

    try:
        subprocess.Popen(
            ["open", url],  # noqa: S603 — URL validated above
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        try:
            subprocess.Popen(
                ["xdg-open", url],  # noqa: S603
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass  # No browser opener available
