"""Tests for scripts/launcher.py stdout/stderr UTF-8 reconfiguration.

Source: issue #96, reporter mbe14 (Windows 11 Pro, cp1252 locale). The
SessionStart hook's stdout is consumed as a pipe by Claude Code's hook
runner; without PYTHONUTF8/PYTHONIOENCODING, CPython encodes with the
process's ANSI code page (cp1252 on the reporter's box), which has no
mapping for U+27E6 "⟦" (the injection-receipt marker header every
SessionStart banner starts with) — the print() then raises
UnicodeEncodeError, crashing the hook and discarding the entire
injection.

cp1252 is a stdlib codec available on every platform (not Windows-only),
so the reporter's own A/B (PYTHONUTF8=1 unset vs set) reproduces exactly
via ``PYTHONIOENCODING=cp1252`` here — no Windows box required.
"""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "launcher.py"


@pytest.fixture
def launcher_module():
    """Load scripts/launcher.py as a module without executing main().

    Named "scripts.launcher" (the dotted path mutmut derives from the
    file's location), not a synthetic name — mutmut keys mutant
    trampolines on the path-derived name, and a synthetic one makes every
    mutant look unreached (issue #262).
    """
    spec = importlib.util.spec_from_file_location("scripts.launcher", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_use_utf8_output_sets_strict_stdout_and_backslashreplace_stderr(
    launcher_module, monkeypatch
):
    """Postcondition: the launcher goes through the shared hook output path,
    so stdout is strict UTF-8 and stderr UTF-8 with backslashreplace."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    launcher_module._use_utf8_output(str(REPO_ROOT))

    assert (out.encoding, out.errors) == ("utf-8", "strict")
    assert (err.encoding, err.errors) == ("utf-8", "backslashreplace")


def test_use_utf8_output_raises_for_a_stream_it_cannot_reconfigure(
    launcher_module, monkeypatch
):
    """A stream without reconfigure() is a hard failure, never skipped."""
    from mcp_server.hooks.output_streams import HookOutputStreamError

    monkeypatch.setattr(sys, "stdout", io.StringIO())
    with pytest.raises(HookOutputStreamError):
        launcher_module._use_utf8_output(str(REPO_ROOT))


def _run_marker_module(
    tmp_path, encoding_env: str | None
) -> subprocess.CompletedProcess:
    """Spawn a real subprocess through launcher.py that prints the exact
    banner header from issue #96 ("## Cortex Memory Context ⟦rcpt:18⟧"),
    with stdout captured as a pipe (mirrors Claude Code's hook runner)."""
    marker_dir = tmp_path / "marker_pkg"
    marker_dir.mkdir()
    (marker_dir / "cortex_marker_mod.py").write_text(
        textwrap.dedent(
            """
            print("## Cortex Memory Context ⟦rcpt:18⟧")
            """
        ),
        encoding="utf-8",
    )

    import os

    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONPATH"] = str(marker_dir) + os.pathsep + env.get("PYTHONPATH", "")
    if encoding_env is not None:
        env["PYTHONIOENCODING"] = encoding_env
    else:
        env.pop("PYTHONIOENCODING", None)

    return subprocess.run(
        [sys.executable, str(LAUNCHER_PATH), "cortex_marker_mod"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
    )


def test_cp1252_pipe_no_longer_crashes_the_launcher(tmp_path):
    """Green-after: with the launcher's UTF-8 reconfigure in place, a
    cp1252-forced pipe still encodes the "⟦" marker successfully
    (utf-8 succeeds outright, nothing is replaced)."""
    result = _run_marker_module(tmp_path, encoding_env="cp1252")
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"charmap" not in result.stderr
    assert b"UnicodeEncodeError" not in result.stderr
    # The marker is emitted as UTF-8 bytes (reconfigure forces utf-8,
    # not cp1252, regardless of PYTHONIOENCODING) — proves the launcher
    # choke point overrides the inherited locale encoding.
    assert "⟦rcpt:18⟧".encode("utf-8") in result.stdout


def test_reproduces_pre_fix_crash_without_the_choke_point(tmp_path, monkeypatch):
    """Red-before: calling print() directly under a cp1252-forced pipe,
    with no reconfigure, reproduces the reporter's exact UnicodeEncodeError
    — proves the failure mode this fix addresses is real, not assumed."""
    marker_dir = tmp_path / "marker_pkg2"
    marker_dir.mkdir()
    script = marker_dir / "no_fix.py"
    script.write_text(
        textwrap.dedent(
            """
            print("## Cortex Memory Context ⟦rcpt:18⟧")
            """
        ),
        encoding="utf-8",
    )
    import os

    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0
    assert b"UnicodeEncodeError" in result.stderr
