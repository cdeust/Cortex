"""The managed PostgreSQL server, for real: pinned archives, start, extensions, stop.

PR #748's review (2026-10-16, blocker 1): pg0 0.15.2's PostgreSQL loads
OpenSSL from Homebrew's absolute path, so on a Mac without Homebrew
``pg0 start`` died in dyld. On macOS this runs the same proof under
``sandbox-exec`` with ``scripts/locked_mac_env/no_homebrew.sb`` (nothing under
/opt/homebrew or /usr/local is readable) and an empty environment; on Linux it
runs as is, so the distribution's own libraries are what the server loads.

It downloads about 13 MB, so it runs where it is asked for: the CI jobs that
set ``CORTEX_MANAGED_PG_E2E=1`` (and anyone who sets it locally).

source: ADR-1114
source: issue #740
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS = REPO_ROOT / "scripts" / "locked_mac_env"
_OPT_IN = "CORTEX_MANAGED_PG_E2E"  # source: ADR-1114 (set by the managed-pg CI jobs)
pytestmark = pytest.mark.skipif(
    os.environ.get(_OPT_IN) != "1" or os.name == "nt",
    reason=f"downloads the pinned archives; set {_OPT_IN}=1 (POSIX only)",
)


def test_setup_then_a_launch_get_a_server_with_vector_and_pg_trgm(tmp_path):
    (tmp_path / "home").mkdir()
    env = [
        "env", "-i", f"HOME={tmp_path / 'home'}", "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        f"TMPDIR={tmp_path}", "LANG=en_US.UTF-8",
    ]  # fmt: skip
    if sys.platform == "darwin":
        env = ["sandbox-exec", "-f", str(_HARNESS / "no_homebrew.sb"), *env]
    done = subprocess.run(
        [*env, sys.executable, "-I", str(_HARNESS / "managed_pg_e2e.py"),
         str(REPO_ROOT), str(tmp_path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    print(done.stdout, done.stderr, sep="\n")
    report = json.loads(done.stdout)
    assert report["passed"], report
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import launcher_pg_assets

    assert report["extensions"]["vector"] == launcher_pg_assets.PGVECTOR_VERSION
    assert done.returncode == 0
