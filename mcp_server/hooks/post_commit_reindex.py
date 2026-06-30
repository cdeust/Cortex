#!/usr/bin/env python3
"""Claude Code PostToolUse hook — re-analyse the code graph after a commit.

This closes the staleness gap the SessionStart TTL leaves open. SessionStart
only re-analyses when the cached graph is older than
``CORTEX_PIPELINE_GRAPH_TTL_HOURS`` (default 24h), so within a working
session the graph drifts behind the source after every commit. This hook
makes a commit the freshness signal: when a ``git commit`` touches
indexable source, it spawns the detached background re-analyse worker so
the next recall / impact query sees the new code — without the user ever
running ``ingest_codebase`` by hand.

Freshness model (two-speed, honest about the limits)
----------------------------------------------------
  * **Trigger:** only on commits that change source the analyzer parses —
    a docs/config-only commit leaves the graph untouched (cheap no-op).
  * **Action:** ``analyze_codebase`` re-parses the *whole* tree. The
    upstream analyzer (ai-automatised-pipeline ``index_codebase``,
    src/indexer/mod.rs) has **no per-file incremental skip** — it walks
    every source file each run. So "incremental" here means *trigger only
    when relevant*, not *re-parse only the changed file*. For
    harness-sized repos a full re-parse is seconds; it runs **detached**
    so it never blocks the commit.
  * **Coalesce / serialise:** a cooldown collapses a burst of commits into
    one re-analyse and keeps two re-analyses from writing the same graph
    directory concurrently. A commit landing inside the cooldown window is
    covered by the next trigger or the SessionStart TTL backstop.

Indexable extensions are taken from the upstream analyzer's language map
(src/parser/mod.rs ``Language::from_extension``) plus the ``.js`` family,
which the indexer covers at the File level via its light-link post-pass.

All failures are non-fatal: this hook must never break the commit flow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_LOG_PREFIX = "[post-commit-reindex]"
_COOLDOWN_FILE = Path("/tmp/cortex_reindex_cooldown.json")


def _cooldown_seconds() -> int:
    raw = os.environ.get("CORTEX_REINDEX_COOLDOWN_SECONDS", "")
    try:
        return max(0, int(raw)) if raw else 120
    except (ValueError, TypeError):
        return 120


# source: ai-automatised-pipeline src/parser/mod.rs Language::from_extension
# (AST-parsed languages) + the indexer's .js-family light-link post-pass
# (File nodes + import edges, no AST symbols).
_INDEXABLE_EXT = {
    "rs",
    "py",
    "ts",
    "tsx",
    "java",
    "kt",
    "kts",
    "swift",
    "m",
    "mm",
    "c",
    "h",
    "cc",
    "cpp",
    "cxx",
    "hh",
    "hpp",
    "hxx",
    "go",
    "js",
    "jsx",
    "mjs",
    "cjs",
}

_COMMIT_FAILED_MARKERS = (
    "nothing to commit",
    "no changes added to commit",
    "did not match any files",
    "untracked files present",
)


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _is_indexable(rel_path: str) -> bool:
    name = rel_path.rsplit("/", 1)[-1]
    if "." not in name:
        return False
    return name.rsplit(".", 1)[-1].lower() in _INDEXABLE_EXT


def _git(root: str, args: list[str]) -> str | None:
    """Run ``git -C root <args>``; return stdout, or None on any error."""
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _changed_source_files(root: str) -> list[str]:
    """Indexable source files in the commit just created (HEAD).

    Uses ``git show`` on HEAD (the commit ``git commit`` produced); falls
    back to a diff against the parent. Returns only paths the analyzer
    parses, so docs/config-only commits yield an empty list.
    """
    out = _git(root, ["show", "--name-only", "--pretty=format:", "HEAD"])
    if out is None:
        out = _git(root, ["diff", "--name-only", "HEAD~1", "HEAD"])
    if not out:
        return []
    files = [line.strip() for line in out.splitlines() if line.strip()]
    return [f for f in files if _is_indexable(f)]


def _commit_failed(event: dict[str, Any]) -> bool:
    """Best-effort: True when the tool output marks a no-op/failed commit.

    When no output is captured we return False (proceed) — a spurious
    re-analyse is harmless; a missed one is the bug we are fixing.
    """
    blob = ""
    for key in ("tool_response", "tool_result", "result", "output"):
        val = event.get(key)
        if isinstance(val, str):
            blob += val
        elif isinstance(val, dict):
            blob += json.dumps(val)
    blob = blob.lower()
    return any(marker in blob for marker in _COMMIT_FAILED_MARKERS)


def _is_commit_command(command: str) -> bool:
    if "git commit" not in command:
        return False
    # Skip forms that don't produce a new commit.
    return not any(flag in command for flag in ("--dry-run", "--help", " -h"))


def _check_cooldown(root: str) -> bool:
    """True when this repo was re-analysed within the cooldown window."""
    try:
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
            last = data.get(root, 0)
            return (time.time() - last) < _cooldown_seconds()
    except Exception:
        pass
    return False


def _update_cooldown(root: str) -> None:
    try:
        data = {}
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
        data[root] = time.time()
        if len(data) > 50:
            newest = sorted(data.items(), key=lambda kv: kv[1], reverse=True)
            data = dict(newest[:50])
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _pipeline_available() -> bool:
    """True when the upstream analyzer is installed (else nothing to do)."""
    try:
        from mcp_server.infrastructure.pipeline_discovery import (
            discover_pipeline_command,
        )

        return discover_pipeline_command() is not None
    except Exception:
        return False


def _spawn_reanalyze(root: str) -> bool:
    """Spawn the detached background re-analyse worker with --reindex.

    Mirrors ``session_start._maybe_background_reanalyze``: own process
    group, stdio redirected to the shared re-analyse log, so this hook
    returns immediately and the commit is never blocked.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
        Path(__file__).resolve().parents[2]
    )
    launcher = Path(plugin_root) / "scripts" / "launcher.py"
    if not launcher.exists():
        return False

    py = shutil.which("python3") or shutil.which("python") or sys.executable
    cmd = [
        py,
        str(launcher),
        "mcp_server.hooks.ingest_codebase_background",
        root,
        "--reindex",
    ]
    log_path = Path.home() / ".claude" / "methodology" / "pipeline_reanalyze.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as log:
            subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        _log(f"spawn failed: {exc}")
        return False
    return True


def process_event(event: dict[str, Any]) -> None:
    if event.get("tool_name") != "Bash":
        return
    command = ((event.get("tool_input") or {}).get("command")) or ""
    if not _is_commit_command(command):
        return
    if _commit_failed(event):
        return

    root = os.environ.get("CLAUDE_PROJECT_ROOT") or os.getcwd()
    if not _pipeline_available():
        return  # No analyzer installed — re-analyse impossible, skip.

    changed = _changed_source_files(root)
    if not changed:
        return  # Docs/config-only commit — the code graph is unaffected.

    if _check_cooldown(root):
        return  # A re-analyse is already coalescing this burst of commits.

    if _spawn_reanalyze(root):
        _update_cooldown(root)
        _log(f"spawned re-analyse for {root} ({len(changed)} source files changed)")


def main() -> None:
    if sys.stdin.isatty():
        return
    raw = sys.stdin.read().strip()
    if not raw:
        return
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return
    try:
        process_event(event)
    except Exception as exc:  # never break the commit flow
        _log(f"unexpected error (ignored): {exc}")


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
