"""install-plugin.sh must persist the backend decision before scripts/setup.py
can fail and exit — issue #633.

Before the fix, ~/.claude/methodology/backend.json was written only after
the setup.py step, guarded by `|| fail ...`. Any setup.py failure (a
Windows torch/torchaudio conflict, a network blip during dependency
install, anything) discarded a correctly-made backend decision. On the
next launch, the missing marker left CORTEX_MEMORY_STORE_BACKEND unset,
and this plugin's "auto" default requires PostgreSQL in CLI-mode runtimes
(mcp_server/infrastructure/memory_store.py) — turning a chosen SQLite
install into a hard PostgreSQL requirement with no PostgreSQL ever
provisioned to satisfy it.

This test drives the real installer against a `python3` stub that fails
only the scripts/setup.py invocation, so the regression reproduces without
needing a genuine environment conflict.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = REPO_ROOT / "scripts" / "install-plugin.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required to drive the installer"
)


def _write_setup_py_stub(bin_dir: Path, *, exit_code: int) -> None:
    """A `python3` on PATH: real Python for everything except
    scripts/setup.py, which exits with `exit_code` immediately -- standing
    in for issue #633's Defect 1 crash (or a clean run) without needing a
    real torch/torchaudio conflict to reproduce either."""
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'for arg in "$@"; do\n'
        '    case "$arg" in\n'
        f"        */scripts/setup.py) exit {exit_code} ;;\n"
        "    esac\n"
        "done\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    mode = stub.stat().st_mode
    stub.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_inert_pip_stubs(bin_dir: Path) -> None:
    """`pip`/`pip3` on PATH that report every package as not installed.

    install-plugin.sh's stale-install pruning (phase 2b) runs `pip3 show
    <pkg>` unconditionally and, on a truthy result, `pip3 uninstall -y
    <pkg>` -- against whatever `pip3` PATH resolves to. Without this stub,
    that resolves to the real interpreter's pip, and in CI it genuinely
    uninstalls this repo's own just-installed editable `hypermnesia-mcp`
    package (a later step in the same job needs it on PATH), because a
    stubbed HOME does not sandbox the real site-packages `pip3` operates
    on. `show` exiting non-zero keeps the uninstall branch unreached."""
    for name in ("pip", "pip3"):
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        mode = stub.stat().st_mode
        stub.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_uname_stub(bin_dir: Path) -> None:
    """A `uname` on PATH that always reports a Windows kernel, so the
    installer's OS dispatch lands on the Windows-postgres branch (which
    reuses the already-stubbable scripts/setup.py invocation) regardless
    of the runner's real OS -- scripts/setup.sh, the Darwin/Linux postgres
    path, needs a genuine PostgreSQL to drive end to end and is not what
    this test is about."""
    stub = bin_dir / "uname"
    stub.write_text("#!/usr/bin/env bash\necho 'MINGW64_NT-10.0'\n", encoding="utf-8")
    mode = stub.stat().st_mode
    stub.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _seed_marker(home: Path, *, backend: str) -> None:
    """Pre-exist a marker as if a previous, presumably-working install had
    already run -- so a test can drive a backend *switch* rather than a
    fresh install."""
    marker_dir = home / ".claude" / "methodology"
    marker_dir.mkdir(parents=True)
    (marker_dir / "backend.json").write_text(
        json.dumps({"backend": backend, "written_by": "test fixture"}),
        encoding="utf-8",
    )


def _run_installer(
    tmp_path: Path,
    *,
    setup_py_exit_code: int,
    cortex_backend: str = "sqlite",
    seed_marker_backend: str | None = None,
    windows: bool = False,
) -> subprocess.CompletedProcess:
    """Drive the real installer, home/PATH isolated under tmp_path, against
    a python3 stub that only fakes scripts/setup.py's own exit code.
    `windows=True` also stubs `uname` so the OS dispatch lands on the
    Windows-postgres branch, which (like the sqlite branch) routes
    through the stubbable scripts/setup.py."""
    home = tmp_path / "home"
    home.mkdir()
    if seed_marker_backend is not None:
        _seed_marker(home, backend=seed_marker_backend)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_setup_py_stub(bin_dir, exit_code=setup_py_exit_code)
    _write_inert_pip_stubs(bin_dir)
    if windows:
        _write_uname_stub(bin_dir)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT),
        "CORTEX_BACKEND": cortex_backend,
    }
    return subprocess.run(
        ["bash", str(INSTALLER_PATH)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _marker_backend(tmp_path: Path) -> str:
    marker = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    assert marker.exists()
    return json.loads(marker.read_text(encoding="utf-8"))["backend"]


def test_marker_persists_backend_even_when_setup_py_fails(tmp_path):
    result = _run_installer(tmp_path, setup_py_exit_code=1)

    # The installer still fails overall — setup.py genuinely failed, and
    # that failure must not be hidden.
    assert result.returncode != 0
    assert "scripts/setup.py failed" in result.stderr

    # But the backend decision itself must survive: a subsequent launch
    # must not silently fall back to requiring PostgreSQL.
    assert _marker_backend(tmp_path) == "sqlite", (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_marker_persists_backend_on_a_successful_sqlite_install(tmp_path):
    """Companion to the failure case: an ordinary successful install still
    persists the marker (the reordering did not just move the write, it
    kept it reachable on the happy path too)."""
    result = _run_installer(tmp_path, setup_py_exit_code=0)

    assert result.returncode == 0, result.stderr
    assert _marker_backend(tmp_path) == "sqlite"


def test_marker_restores_previous_backend_when_switch_setup_fails(tmp_path):
    """A working sqlite marker must survive a failed attempt to switch to
    postgresql -- the fix for issue #633 introduced this regression: it
    persists the newly-*requested* backend before setup runs, so a failed
    switch away from a working install left the marker pointing at a
    backend that was never actually stood up, reproducing #633's own bug
    in reverse."""
    result = _run_installer(
        tmp_path,
        setup_py_exit_code=1,
        cortex_backend="postgres",
        seed_marker_backend="sqlite",
        windows=True,
    )

    # The switch genuinely failed and that must not be hidden.
    assert result.returncode != 0

    # But the marker must still say sqlite: postgresql was requested,
    # never confirmed working, and must not silently become the new
    # requirement on next launch.
    assert _marker_backend(tmp_path) == "sqlite", (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
