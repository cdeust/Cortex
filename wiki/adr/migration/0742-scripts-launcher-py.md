# ADR-0742: scripts/launcher.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/launcher.py`; original SHA-256 `91d351ee4197c6736cdd80e35eaa832f8edbef38595aa9e757ca53e4157b2173`.

## Original comment, lines 23–29

````text
# launcher_deps.py is a stdlib-only sibling module (dependency bootstrap
# logic extracted for SRP + the 500-line file-size rule). Path-based
# import (not a bare `import launcher_deps`) so this resolves identically
# whether launcher.py is run directly (`python3 scripts/launcher.py`,
# where Python auto-adds the script's directory to sys.path) or loaded
# via importlib.util.spec_from_file_location from a test, whose sys.path
# does not include scripts/ by default.
````

## Original comment, lines 35–35

````text
# source: structural — program name + <module>
````

## Original docstring, lines 57–84

````text
"""Force UTF-8 encoding on stdout/stderr, replacing unencodable chars.

    Precondition: none — safe to call unconditionally, before argv parsing.
    Postcondition: sys.stdout and sys.stderr each either (a) have
    encoding="utf-8" and errors="replace", or (b) are left untouched if
    reconfigure() is unavailable/fails — never raises.

    On Windows, a hook's stdout is a pipe (Claude Code's hook runner)
    rather than a console, so CPython falls back to the process's ANSI
    code page (e.g. cp1252) unless PYTHONUTF8/PYTHONIOENCODING is set.
    Any injected memory-context content containing a non-cp1252
    character (the "⟦rcpt:N⟧" injection-receipt marker is one; so is
    other emoji/non-Latin text a memory might legitimately contain)
    then raises UnicodeEncodeError from print(), which crashes the hook
    process and silently discards the ENTIRE SessionStart injection —
    not just the offending line (source: issue #96, reporter mbe14,
    verified A/B: PYTHONUTF8=1 vs unset on Windows 11 cp1252).

    Claude Code consumes hook stdout as UTF-8 regardless of the host
    locale, so forcing utf-8 here is what the consumer already expects;
    errors="replace" is a defense-in-depth fallback for any character
    not exercised by the reporter's A/B.

    reconfigure() is a TextIOWrapper method (Python 3.7+); it can raise
    if the stream isn't a TextIOWrapper (e.g. already replaced by a
    test harness) — caught per-stream so one stream's failure can't
    skip the other's.
    """
````

## Original comment, lines 93–99

````text
# Choke point: every entry point (MCP server, every hook, every
    # detached background worker) runs through this main() — see
    # .claude-plugin/plugin.json (mcpServers + hooks.*) and the
    # background-worker Popen calls in session_start.py /
    # post_commit_reindex.py, all of which invoke
    # `python3 scripts/launcher.py <module>`. Reconfiguring here covers
    # every one of them from a single site (issue #96).
````

## Original comment, lines 163–168

````text
# Install deps. The base-deps check is a stamp-gated no-op once a
    # prior call has confirmed the current pins are satisfied (issue
    # #97 suggestion 3) — every entry point (server, hooks, doctor)
    # imports the same base stack and crashes the same way if anything
    # is missing. SessionStart additionally needs the heavy ML stack
    # (sentence-transformers, flashrank).
````

