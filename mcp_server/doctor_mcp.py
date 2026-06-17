"""`cortex-doctor mcp` — end-to-end MCP startup diagnostics.

Helps Discord/issue-tracker users diagnose "MCP server failed to start"
without staring at silent errors. Every check reports what command was
attempted and the exact error if it failed — never just "broken."

Checks performed (in order):
  * Python interpreter — `which python3`, `which python`, `python --version`
  * `~/.claude/plugins/installed_plugins.json` — exists, parses, key
    `cortex@cortex-plugins` present, installPath valid, launcher present
  * `CLAUDE_PLUGIN_ROOT` env var presence (informational — only set by
    Claude Code at hook/MCP spawn time, normally absent in shells)
  * Launcher smoke probe: spawn the launcher with no module argv and
    assert the usage-and-exit-1 contract.
  * `DATABASE_URL` presence + URL parse
  * PostgreSQL reachable — `SELECT 1` against the configured DSN
  * PostgreSQL extensions — enumerate `vector`, `pg_trgm` via pg_extension
  * Critical Python deps importable (psycopg, pgvector, fastmcp, pydantic,
    sentence_transformers)

What we explicitly do NOT check (Feynman discipline — say "I don't know"
when a probe is unreliable):
  * MCP stdio handshake. Spawning the actual server, sending an
    `initialize` JSON-RPC frame, and reading the response is a moving
    target (FastMCP version, transport buffering, race against the
    server's own dependency-install step in launcher.py). A flaky check
    is worse than no check — it sends users chasing phantom failures.
    Status: not implemented; reported as "I don't know" in --json so the
    consumer knows it was deliberately skipped.

Output:
  - Human-readable by default (one line per check + actionable fix).
    ANSI colour when stdout is a TTY (green=ok, red=fail, yellow=warn).
  - `--json` flag emits a machine-readable report (Discord-paste friendly).
  - `--copy` flag adds a header that tells users where to paste the output.

This module is invoked from `cortex-doctor mcp` via `mcp_server.doctor.run`
(the entry point registered in pyproject.toml).

Source: Discord report 2026-05-09 (MCP server "✘ failed" with no
actionable error). Root cause was a fragile inline `python -c` wrapper in
`.mcp.json` that swallowed launcher startup errors.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mcp_server.shared.redaction import redact_url, scrub_secrets


@dataclass
class McpCheck:
    """One MCP-startup diagnostic result."""

    name: str
    ok: bool
    detail: str
    fix: str = ""
    attempted: str = ""  # the exact command/path probed
    error: str = ""  # exact error string if failed
    severity: str = "fail"  # "fail" | "warn" | "ok" — drives colour + exit


@dataclass
class McpReport:
    """Aggregated report from all MCP checks."""

    checks: list[McpCheck] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # "I don't know" probes

    @property
    def required_fails(self) -> list[McpCheck]:
        return [c for c in self.checks if not c.ok and c.severity == "fail"]

    @property
    def warnings(self) -> list[McpCheck]:
        return [c for c in self.checks if not c.ok and c.severity == "warn"]

    def to_dict(self) -> dict:
        return {
            "checks": [asdict(c) for c in self.checks],
            "skipped": list(self.skipped),
            "ok": not self.required_fails,
            "fail_count": len(self.required_fails),
            "warn_count": len(self.warnings),
        }


# --- individual checks --------------------------------------------------
# Each check is independent. None swallow exceptions silently — every
# unexpected exception is captured and surfaced via McpCheck.error.


def _check_python_interpreter() -> McpCheck:
    """Confirm a usable python interpreter exists on PATH.

    `.mcp.json` invokes `python3` directly. On Windows, the launcher
    binary is often `python` or `py`; on some Linux distros only one
    of `python3`/`python` exists. We report which were found AND the
    version reported by the first found.

    Source: mcp_server/doctor_mcp.py — Discord triage rule #1.
    """
    found = []
    version_str = ""
    for cmd in ("python3", "python", "py"):
        path = shutil.which(cmd)
        if path:
            found.append(f"{cmd}={path}")
            if not version_str:
                # Capture the version reported by `python3 --version`.
                # If it crashes (corrupt install), surface the error.
                try:
                    proc = subprocess.run(
                        [path, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    raw = (proc.stdout or proc.stderr or "").strip()
                    version_str = raw or "(no output)"
                except (OSError, subprocess.SubprocessError) as exc:
                    version_str = f"({type(exc).__name__}: {exc})"
    if not found:
        return McpCheck(
            name="python interpreter",
            ok=False,
            detail="no python found on PATH",
            attempted="which python3 / python / py",
            fix="Install Python 3.10+ and ensure `python3` is on PATH. "
            "On Windows: `py -3` or add Python to PATH. "
            "On Linux: `apt install python3` / `dnf install python3`.",
        )
    return McpCheck(
        name="python interpreter",
        ok=True,
        detail=f"{'; '.join(found)}; version={version_str}",
        attempted="which python3 / python / py; python3 --version",
        severity="ok",
    )


def _installed_plugins_path() -> Path:
    return Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def _check_installed_plugins_json() -> tuple[McpCheck, dict | None]:
    """Validate ~/.claude/plugins/installed_plugins.json shape.

    Returns the check + the parsed JSON (or None) so subsequent checks
    can reuse it without re-reading.
    """
    path = _installed_plugins_path()
    attempted = str(path)
    if not path.exists():
        return (
            McpCheck(
                name="installed_plugins.json exists",
                ok=False,
                detail="not found",
                attempted=attempted,
                fix="Install Cortex via Claude Code: "
                "`/plugin install cortex@cortex-plugins`. "
                "If installed but file missing, re-run the install.",
            ),
            None,
        )
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return (
            McpCheck(
                name="installed_plugins.json parseable",
                ok=False,
                detail="invalid JSON",
                attempted=attempted,
                error=f"{type(exc).__name__}: {exc}",
                fix=f"File at {path} is corrupt. Re-install Cortex.",
            ),
            None,
        )
    except OSError as exc:
        return (
            McpCheck(
                name="installed_plugins.json readable",
                ok=False,
                detail="cannot read file",
                attempted=attempted,
                error=f"{type(exc).__name__}: {exc}",
                fix=f"Check permissions: `ls -la {path}`",
            ),
            None,
        )
    # Print a compact shape summary so the Discord paste is self-contained.
    plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
    keys = (
        list(plugins.keys()) if isinstance(plugins, dict) else "(plugins not an object)"
    )
    return (
        McpCheck(
            name="installed_plugins.json parseable",
            ok=True,
            detail=f"valid JSON; plugins keys = {keys}",
            attempted=attempted,
            severity="ok",
        ),
        data,
    )


def _check_cortex_plugin_entry(data: dict | None) -> tuple[McpCheck, str | None]:
    """Look up the cortex@cortex-plugins entry and return its installPath."""
    if data is None:
        return (
            McpCheck(
                name="cortex plugin entry",
                ok=False,
                detail="installed_plugins.json unavailable",
            ),
            None,
        )
    plugins = data.get("plugins", {})
    entries = plugins.get("cortex@cortex-plugins")
    if not entries:
        keys = list(plugins.keys())
        return (
            McpCheck(
                name="cortex plugin entry",
                ok=False,
                detail=f"key 'cortex@cortex-plugins' missing; found: {keys}",
                fix="Re-install: `/plugin install cortex@cortex-plugins`. "
                "If you installed under a custom marketplace name, the "
                "key shape will differ — `.mcp.json` now uses "
                "${CLAUDE_PLUGIN_ROOT} substitution and no longer needs "
                "this key.",
            ),
            None,
        )
    if not isinstance(entries, list) or not entries:
        return (
            McpCheck(
                name="cortex plugin entry",
                ok=False,
                detail=f"unexpected shape: {type(entries).__name__}",
            ),
            None,
        )
    entry = entries[0]
    install_path = entry.get("installPath")
    if not install_path:
        return (
            McpCheck(
                name="cortex plugin entry",
                ok=False,
                detail="installPath field missing",
            ),
            None,
        )
    return (
        McpCheck(
            name="cortex plugin entry",
            ok=True,
            detail=f"installPath={install_path}",
            severity="ok",
        ),
        install_path,
    )


def _check_install_path(install_path: str | None) -> McpCheck:
    """Confirm installPath exists and contains scripts/launcher.py."""
    if not install_path:
        return McpCheck(
            name="installPath valid",
            ok=False,
            detail="no installPath to check",
        )
    p = Path(install_path)
    if not p.is_dir():
        return McpCheck(
            name="installPath valid",
            ok=False,
            detail="directory does not exist",
            attempted=install_path,
            fix=f"Stale installPath after upgrade. Re-install Cortex "
            f"or remove the stale entry from {_installed_plugins_path()}.",
        )
    launcher = p / "scripts" / "launcher.py"
    if not launcher.is_file():
        return McpCheck(
            name="installPath valid",
            ok=False,
            detail="scripts/launcher.py missing",
            attempted=str(launcher),
            fix="installPath exists but is not a Cortex install. Re-install Cortex.",
        )
    return McpCheck(
        name="installPath valid",
        ok=True,
        detail=str(launcher),
        attempted=str(launcher),
        severity="ok",
    )


def _check_claude_plugin_root_env() -> McpCheck:
    """Report CLAUDE_PLUGIN_ROOT presence (informational).

    This var is set by Claude Code only at hook/MCP spawn time, so its
    absence from a shell is normal. We report it for completeness — when
    debugging from inside a hook or MCP context, its presence confirms
    Claude Code is doing variable substitution correctly.
    """
    val = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if val:
        return McpCheck(
            name="CLAUDE_PLUGIN_ROOT (env)",
            ok=True,
            detail=val,
            severity="ok",
        )
    return McpCheck(
        name="CLAUDE_PLUGIN_ROOT (env)",
        ok=True,  # informational — not a failure
        detail="not set (normal in interactive shells; set by Claude Code "
        "at MCP/hook spawn)",
        severity="ok",
    )


def _check_launcher_smoke(install_path: str | None) -> McpCheck:
    """Probe `python launcher.py` to catch silent startup errors.

    The original `.mcp.json` used `python3 -c '...os.execvp(...)'` which
    swallows launcher startup errors invisibly. We invoke the launcher
    with no module argv and capture exit code + stderr. Expected outcome:
    exit 1 with "Usage:" on stderr (the launcher's own argv-validation).
    Any other state — non-1 exit, missing usage, stack trace — is a real
    launcher problem the user needs to see.

    Source: scripts/launcher.py:127-134 (the usage-and-exit-1 branch).
    """
    if not install_path:
        return McpCheck(
            name="launcher import smoke",
            ok=False,
            detail="no install path to probe",
        )
    launcher = Path(install_path) / "scripts" / "launcher.py"
    if not launcher.is_file():
        return McpCheck(
            name="launcher import smoke",
            ok=False,
            detail="launcher.py missing",
            attempted=str(launcher),
        )
    py = shutil.which("python3") or shutil.which("python") or sys.executable
    cmd = [py, str(launcher)]
    attempted = " ".join(cmd)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return McpCheck(
            name="launcher import smoke",
            ok=False,
            detail="failed to spawn launcher",
            attempted=attempted,
            error=f"{type(exc).__name__}: {exc}",
        )
    stderr = proc.stderr or ""
    if proc.returncode == 1 and "Usage:" in stderr:
        return McpCheck(
            name="launcher import smoke",
            ok=True,
            detail="launcher loads cleanly (usage printed)",
            attempted=attempted,
            severity="ok",
        )
    return McpCheck(
        name="launcher import smoke",
        ok=False,
        detail=f"unexpected exit {proc.returncode}",
        attempted=attempted,
        error=stderr.strip() or (proc.stdout or "").strip() or "no output",
        fix="Run the command above by hand to see the full error. "
        "Common causes: corrupt install, python version <3.10, "
        "missing stdlib modules.",
    )


def _check_database_url() -> McpCheck:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return McpCheck(
            name="DATABASE_URL",
            ok=False,
            detail="not set",
            fix="Set in shell or .mcp.json env: "
            "DATABASE_URL=postgresql://localhost:5432/cortex",
        )
    if not url.startswith(("postgresql://", "postgres://")):
        return McpCheck(
            name="DATABASE_URL",
            ok=False,
            detail=f"unexpected scheme: {url[:20]}...",
            fix="Use postgresql:// scheme.",
        )
    return McpCheck(name="DATABASE_URL", ok=True, detail=redact_url(url), severity="ok")


def _check_pg_reachable() -> McpCheck:
    """Open a real connection and run `SELECT 1`.

    Verbatim error capture is the whole point of this check — connection
    failures are the most common Discord-paste root cause and the user
    needs to see psycopg's actual error string, not a paraphrase.

    Source: psycopg 3 docs — psycopg.connect(dsn, connect_timeout=...).
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return McpCheck(
            name="postgresql reachable",
            ok=False,
            detail="DATABASE_URL not set; cannot connect",
            fix="Set DATABASE_URL first.",
        )
    try:
        import psycopg
    except ImportError as exc:
        return McpCheck(
            name="postgresql reachable",
            ok=False,
            detail="psycopg not installed",
            error=f"{type(exc).__name__}: {exc}",
            fix="Install: `pip install psycopg[binary]>=3.1`",
        )
    attempted = f"psycopg.connect({redact_url(url)!r}); cur.execute('SELECT 1')"
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            row = conn.execute("SELECT 1").fetchone()
    except Exception as exc:
        # Catch-all here is intentional: psycopg raises a wide variety of
        # subclasses (OperationalError, DatabaseError, etc.) and we want
        # the precise exception type + message in the report.
        # scrub_secrets guards against psycopg OperationalError embedding the
        # full DSN (including password) in its message on connection failure.
        return McpCheck(
            name="postgresql reachable",
            ok=False,
            detail="connection failed",
            attempted=attempted,
            error=scrub_secrets(f"{type(exc).__name__}: {exc}"),
            fix="Check that PostgreSQL is running and the DSN is correct. "
            "macOS Homebrew: `brew services start postgresql@17`. "
            "Verify with: `psql \"$DATABASE_URL\" -c 'SELECT 1'`.",
        )
    if row != (1,):
        return McpCheck(
            name="postgresql reachable",
            ok=False,
            detail=f"unexpected SELECT 1 result: {row}",
            attempted=attempted,
        )
    return McpCheck(
        name="postgresql reachable",
        ok=True,
        detail="SELECT 1 returned (1,)",
        attempted=attempted,
        severity="ok",
    )


def _check_pg_extensions() -> McpCheck:
    """Enumerate installed extensions; report whether vector + pg_trgm exist.

    Cortex requires both. Source: mcp_server/infrastructure/pg_schema.py
    (CREATE EXTENSION IF NOT EXISTS vector / pg_trgm).
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return McpCheck(
            name="postgresql extensions",
            ok=False,
            detail="DATABASE_URL not set",
        )
    try:
        import psycopg
    except ImportError as exc:
        return McpCheck(
            name="postgresql extensions",
            ok=False,
            detail="psycopg not installed",
            error=f"{type(exc).__name__}: {exc}",
        )
    attempted = "SELECT extname FROM pg_extension"
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            rows = conn.execute(attempted).fetchall()
    except Exception as exc:
        # scrub_secrets guards against psycopg OperationalError embedding the
        # full DSN (including password) in its message on connection failure.
        return McpCheck(
            name="postgresql extensions",
            ok=False,
            detail="query failed",
            attempted=attempted,
            error=scrub_secrets(f"{type(exc).__name__}: {exc}"),
        )
    names = sorted({r[0] for r in rows})
    missing = sorted({"vector", "pg_trgm"} - set(names))
    if missing:
        return McpCheck(
            name="postgresql extensions",
            ok=False,
            detail=f"installed: {names}; missing: {missing}",
            attempted=attempted,
            fix='psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS '
            'vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"',
        )
    return McpCheck(
        name="postgresql extensions",
        ok=True,
        detail=f"installed: {names}",
        attempted=attempted,
        severity="ok",
    )


# Critical imports the MCP server pulls in at startup. sentence_transformers
# is heavy (downloads ML weights) but session_start hook needs it; we check
# it as warn rather than fail because a non-session-start MCP startup will
# still work without it.
_HARD_DEPS = ("fastmcp", "pydantic", "psycopg", "pgvector")
_SOFT_DEPS = ("sentence_transformers",)


def _check_critical_imports() -> McpCheck:
    """Verify the Python deps the MCP server hard-imports at startup.

    Source: scripts/launcher.py:_ensure_deps for the hard list,
    _ensure_all_deps for sentence_transformers (session_start path).
    """
    missing = []
    errs = []
    for mod in _HARD_DEPS:
        try:
            __import__(mod)
        except ImportError as exc:
            missing.append(mod)
            errs.append(f"{mod}: {exc}")
    if missing:
        return McpCheck(
            name="critical Python deps",
            ok=False,
            detail=f"missing: {', '.join(missing)}",
            error="\n".join(errs),
            fix="The launcher auto-installs deps on first run; if this "
            "check still fails, run by hand: "
            "`pip install fastmcp pydantic psycopg[binary] pgvector`",
        )
    return McpCheck(
        name="critical Python deps",
        ok=True,
        detail=f"importable: {', '.join(_HARD_DEPS)}",
        severity="ok",
    )


def _check_optional_imports() -> McpCheck:
    """Verify ML deps used by the SessionStart hook.

    Reported as warn (not fail) because the MCP server itself starts
    fine without sentence_transformers — only the SessionStart hook
    needs it. Users hitting "MCP server failed" usually have a hard-dep
    failure; sentence_transformers is informational.
    """
    missing = []
    errs = []
    for mod in _SOFT_DEPS:
        try:
            __import__(mod)
        except ImportError as exc:
            missing.append(mod)
            errs.append(f"{mod}: {exc}")
    if missing:
        return McpCheck(
            name="optional Python deps (session_start hook)",
            ok=False,
            severity="warn",
            detail=f"missing: {', '.join(missing)}",
            error="\n".join(errs),
            fix="MCP server starts without these; only SessionStart hook "
            "needs them. To install: "
            "`pip install sentence-transformers>=2.2.0 flashrank>=0.2.0`",
        )
    return McpCheck(
        name="optional Python deps (session_start hook)",
        ok=True,
        detail=f"importable: {', '.join(_SOFT_DEPS)}",
        severity="ok",
    )


# --- orchestration -------------------------------------------------------


def _skipped_stdio_handshake() -> dict:
    """Return the structured "I don't know" record for the MCP handshake.

    Feynman discipline: a flaky check is worse than no check. We declare
    this skipped explicitly so the consumer of --json knows it's a
    deliberate omission, not a bug.
    """
    return {
        "name": "MCP stdio handshake (initialize → response)",
        "skipped": True,
        "reason": "Spawning the FastMCP server, sending initialize, and "
        "reading the response is a flaky probe across versions and racy "
        "with the launcher's own dep-install step. Reporting 'I don't "
        "know' rather than a false signal.",
    }


def collect_mcp_report() -> McpReport:
    """Run every MCP check and return the aggregated report.

    Pure: takes no args, returns a value. The CLI wrapper handles output.
    """
    report = McpReport()
    report.checks.append(_check_python_interpreter())

    plugins_check, data = _check_installed_plugins_json()
    report.checks.append(plugins_check)

    entry_check, install_path = _check_cortex_plugin_entry(data)
    report.checks.append(entry_check)

    report.checks.append(_check_install_path(install_path))
    report.checks.append(_check_claude_plugin_root_env())
    report.checks.append(_check_launcher_smoke(install_path))
    report.checks.append(_check_database_url())
    report.checks.append(_check_pg_reachable())
    report.checks.append(_check_pg_extensions())
    report.checks.append(_check_critical_imports())
    report.checks.append(_check_optional_imports())
    report.skipped.append(_skipped_stdio_handshake())
    return report


# --- output formatting -------------------------------------------------

# ANSI codes — only emitted when stdout is a TTY (prevents garbage in
# pipes, files, and Discord pastes; users running interactively still
# see the colour cues).
_ANSI_RESET = "\033[0m"
_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_YELLOW = "\033[33m"


def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


def _mark(check: McpCheck, colour: bool) -> str:
    """Return the status mark for a check, optionally coloured."""
    if check.ok:
        symbol, ansi = "OK  ", _ANSI_GREEN
    elif check.severity == "warn":
        symbol, ansi = "WARN", _ANSI_YELLOW
    else:
        symbol, ansi = "FAIL", _ANSI_RED
    if colour:
        return f"{ansi}[{symbol}]{_ANSI_RESET}"
    return f"[{symbol}]"


def _print_human(report: McpReport, copy_header: bool = False) -> None:
    colour = _colour_enabled()
    if copy_header:
        print("# cortex-doctor mcp output (please paste in Discord/issue)")
        print()
    print("Cortex doctor — MCP startup diagnostics")
    print("=" * 60)
    width = max(len(c.name) for c in report.checks) + 2
    for c in report.checks:
        print(f"  {_mark(c, colour)} {c.name.ljust(width)} {c.detail}")
        if c.attempted and not c.ok:
            print(f"         attempted: {c.attempted}")
        if c.error:
            for line in c.error.splitlines():
                print(f"         error: {line}")
    for skip in report.skipped:
        marker = f"{_ANSI_YELLOW}[SKIP]{_ANSI_RESET}" if colour else "[SKIP]"
        print(f"  {marker} {skip['name']}")
        print(f"         reason: {skip['reason']}")
    print("=" * 60)
    fails = report.required_fails
    warns = report.warnings
    if not fails and not warns:
        print("All MCP checks passed. Cortex MCP should start cleanly.")
        return
    if fails:
        print(f"{len(fails)} required check(s) failed. Fixes:")
        for i, c in enumerate(fails, 1):
            print(f"  {i}. {c.name}:")
            if c.fix:
                for line in c.fix.splitlines():
                    print(f"     → {line}")
            else:
                print(f"     → Review output above: {c.detail}")
    if warns:
        print(
            f"\n{len(warns)} warning(s) (MCP server still starts, "
            "feature may be limited):"
        )
        for i, c in enumerate(warns, 1):
            print(f"  {i}. {c.name}:")
            if c.fix:
                for line in c.fix.splitlines():
                    print(f"     → {line}")
            else:
                print(f"     → Review output above: {c.detail}")


def run_mcp(json_output: bool = False, copy_header: bool = False) -> int:
    """Entry point for `cortex-doctor mcp`.

    Returns 0 on full green (or warn-only), 1 on any required failure.
    """
    report = collect_mcp_report()
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_human(report, copy_header=copy_header)
    return 0 if not report.required_fails else 1
