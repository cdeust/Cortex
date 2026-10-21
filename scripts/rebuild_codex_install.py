"""Rebuild the Codex uv-tool install of Cortex from THIS commit (ADR-1112).

    python3 scripts/rebuild_codex_install.py          # print the plan, change nothing
    python3 scripts/rebuild_codex_install.py --yes    # build, install, verify

Why: the Codex plugin's ``runtime.py setup`` checks only the version label of
the installed wheel. On 2026-10-21 the owner's Codex install was a 4.23.5
wheel built on 2026-10-02 from another commit, whose schema fingerprint
(c8674541...) differs from the Claude plugin's 4.23.5 (44002703...); every
start of either re-applied its DDL on the shared store
(docs/verification/connection-broker/experiment-log.md entries 2 and 7).
Since ADR-1112 a versioned Cortex refuses a store that an unversioned
install rewrote (``SchemaTamperedError``); this script removes the cause by
installing a wheel built from the same commit as the running plugin.

Steps (``--yes``): refuse a dirty tree; ``uv build --wheel`` into a temporary
directory; ``uv tool install --force --no-build`` of that wheel with the
``postgresql`` and ``sqlite`` extras (the set ``runtime.py setup`` installs);
check that the installed tree's schema fingerprint equals this checkout's;
print the one remaining step, ``python -m mcp_server.migrate``.

source: ADR-1112
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

# source: ADR-1112 repository root, from this file's location
ROOT = Path(__file__).resolve().parents[1]
# source: plugins/hypermnesia-mcp-codex/scripts/runtime.py requirement()
EXTRAS = "postgresql,sqlite"
# source: ADR-1112 what the installed tree must report
_FINGERPRINT = (
    "from mcp_server.infrastructure.pg_schema_fingerprint import compute_ddl_hash;"
    " print(compute_ddl_hash())"
)


def plan(wheel_dir: Path, python: str) -> list[list[str]]:
    """The two commands that rebuild and reinstall, in order."""
    return [
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), str(ROOT)],
        [
            "uv",
            "tool",
            "install",
            "--force",
            "--python",
            python,
            "--no-build",
            f"hypermnesia-mcp[{EXTRAS}] @ <wheel built in {wheel_dir}>",
        ],
    ]


def _clean_head() -> str:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        raise SystemExit("refusing: the working tree has uncommitted changes")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()


def _installed_fingerprint() -> str:
    tool_dir = subprocess.check_output(["uv", "tool", "dir"], text=True).strip()
    runtime = Path(tool_dir) / "hypermnesia-mcp"
    python = runtime / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    return subprocess.check_output(
        [str(python), "-I", "-c", _FINGERPRINT], text=True
    ).strip()


def _execute(python: str) -> None:
    sys.path.insert(0, str(ROOT))
    from mcp_server.infrastructure.pg_schema_fingerprint import compute_ddl_hash  # noqa: PLC0415 -- this checkout, no driver needed

    head = _clean_head()
    with tempfile.TemporaryDirectory(prefix="cortex-codex-wheel-") as scratch:
        build, install = plan(Path(scratch), python)
        subprocess.run(build, check=True)
        wheels = sorted(Path(scratch).glob("hypermnesia_mcp-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected one wheel in {scratch}, found {len(wheels)}")
        install[-1] = f"hypermnesia-mcp[{EXTRAS}] @ {wheels[0].as_uri()}"
        subprocess.run(install, check=True)
    installed, expected = _installed_fingerprint(), compute_ddl_hash()
    if installed != expected:
        raise SystemExit(f"installed fingerprint {installed[:16]} != {expected[:16]}")
    print(f"Codex install rebuilt from {head}; schema fingerprint {expected[:16]}.")
    print("Next: python -m mcp_server.migrate (records the schema version once).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="build and install")
    parser.add_argument("--python", default=sys.executable, help="native interpreter")
    args = parser.parse_args()
    if not args.yes:
        for command in plan(Path("<temporary directory>"), args.python):
            print(" ".join(command))
        print("dry run: nothing changed; add --yes to build and install")
        return 0
    _execute(args.python)
    return 0


if __name__ == "__main__":
    sys.exit(main())
