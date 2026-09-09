"""Repo-wide gate: every hashed constraint install must pass --no-deps.

``mcp_server/hooks/no_deps_gate.py`` blocks the same shape at edit time for
Claude Code; this script closes the gap that leaves open — a commit made by
any other tool, or a file that predates the hook. Both share one detector,
``mcp_server.hooks._no_deps_lex``, so there is exactly one definition of
"violates the invariant" (ADR-1062).

Usage::

    python scripts/check_no_deps_invariant.py                 # tracked files
    python scripts/check_no_deps_invariant.py path/to/file.sh  # explicit files

Exit codes: 0 clean, 1 a violation was found, 2 could not enumerate tracked
files (git failed and no paths were given explicitly).

source: ADR-1062"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_PROJECT_ROOT = str(REPO_ROOT)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from mcp_server.hooks import _no_deps_lex as lex  # noqa: E402
from mcp_server.hooks.no_deps_gate import in_scope  # noqa: E402

# The pathspecs git ls-files needs to enumerate ADR-1062's scope — a mirror
# of no_deps_gate.in_scope expressed as globs, since git filters files
# faster than a full-tree Python walk would.
_PATHSPECS = (
    "scripts/*",
    ".github/workflows/*",
    ".github/actions/*",
    ".devcontainer/*",
    "Dockerfile*",
    "**/Dockerfile*",
)


def tracked_files() -> list[str] | None:
    """Tracked files under ADR-1062's scope, or None if git could not answer."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", *_PATHSPECS],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def scan(rel_paths: list[str]) -> list[tuple[str, int, str]]:
    """(path, line, command) for every violation across ``rel_paths``.

    Precondition: paths are relative to REPO_ROOT. A path that does not
    exist, cannot be decoded, or falls outside ``in_scope`` contributes
    nothing.
    Postcondition: [] iff every scoped, hash-pinned install in the scanned
    files also carries --no-deps.
    """
    found: list[tuple[str, int, str]] = []
    for rel_path in rel_paths:
        if not in_scope(rel_path):
            continue
        full_path = REPO_ROOT / rel_path
        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line, command in lex.find_violations(content):
            found.append((rel_path, line, command))
    return found


def _report(violations: list[tuple[str, int, str]]) -> None:
    print(
        f"no-deps-invariant gate: {len(violations)} install(s) combine "
        f"{lex.REQUIRE_HASHES} with a requirements-file install but omit "
        f"{lex.NO_DEPS}:",
        file=sys.stderr,
    )
    for path, line, command in violations:
        print(f"  {path}:{line}: {command}", file=sys.stderr)
    print(
        "\nThe file installed is the complete uv-resolved dependency "
        f"closure; without {lex.NO_DEPS} pip re-derives it from raw "
        "metadata and can abort with ResolutionImpossible (ADR-1062, "
        "ADR-0800, ADR-1059). Add the flag to each command above.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths", nargs="*", help="Explicit files to check instead of the tracked scope"
    )
    args = parser.parse_args(argv)

    rel_paths = args.paths or tracked_files()
    if rel_paths is None:
        print(
            "no-deps-invariant gate: could not enumerate tracked files "
            "(git ls-files failed) and no paths were given explicitly.",
            file=sys.stderr,
        )
        return 2

    violations = scan(rel_paths)
    if not violations:
        print(f"no-deps-invariant gate: clean ({len(rel_paths)} file(s) scanned).")
        return 0
    _report(violations)
    return 1


if __name__ == "__main__":
    sys.exit(main())
