"""scripts/launcher_uv.py: the locked-set export and install commands.

source: ADR-1092"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests_py.scripts._launcher_uv_fixture import REPO_ROOT
from tests_py.scripts._launcher_uv_fixture import done as _done


def test_export_and_install_commands_are_locked_and_hash_checked(uv_mod):
    export = uv_mod.export_command("uv", ("--extra", "x"), Path("o/pylock.a.toml"))
    assert export == [
        "uv", "export", "--quiet", "--frozen", "--no-config", "--project",
        str(REPO_ROOT), "--no-emit-project", "--no-default-groups", "--extra", "x",
        "--format", "pylock.toml", "--output-file", str(Path("o/pylock.a.toml")),
    ]  # fmt: skip
    install = uv_mod.install_command("uv", Path("pylock.a.toml"), "scratch")
    assert install == [
        "uv", "pip", "install", "--quiet", "--no-config", "--preview-features",
        "pylock", "--python", sys.executable, "--require-hashes", "--target",
        "scratch", "-r", "pylock.a.toml",
    ]  # fmt: skip


DROPPED = ("UV_NO_VERIFY_HASHES", "UV_LOCKED", "UV_FROZEN", "UV_PYTHON")


def test_environment_drops_settings_that_weaken_the_install(uv_mod, monkeypatch):
    for name in (*DROPPED, "UV_PROJECT_ENVIRONMENT"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("UV_CACHE_DIR", "kept")
    env = uv_mod.environment()
    assert env["UV_CACHE_DIR"] == "kept"
    assert not {*DROPPED, "UV_PROJECT_ENVIRONMENT"} & set(env)


@pytest.fixture
def uv_runs(uv_mod, monkeypatch) -> list:
    """Every subprocess.run of install_locked_set; locate answers "uv"."""
    runs: list = []
    located = []
    monkeypatch.setattr(uv_mod, "locate", lambda d: located.append(d) or "uv")
    monkeypatch.setenv("UV_FROZEN", "1")
    runs.append(located)
    return runs


def test_install_stops_at_a_failed_export(uv_mod, monkeypatch, uv_runs):
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda cmd, **k: uv_runs.append((cmd, k)) or _done(2)
    )
    result = uv_mod.install_locked_set("deps", ("--only-group", "g"), "scratch")
    assert result.returncode == 2
    assert [cmd[1] for cmd, _k in uv_runs[1:]] == ["export"]


def test_install_feeds_the_exported_pylock_to_uv_pip(uv_mod, monkeypatch, uv_runs):
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda cmd, **k: uv_runs.append((cmd, k)) or _done()
    )
    group = ("--only-group", "g")
    assert uv_mod.install_locked_set("deps", group, "t").returncode == 0
    (export, export_kw), (install, install_kw) = uv_runs[1:]
    pylock = Path(export[export.index("--output-file") + 1])
    assert uv_runs[0] == ["deps"]
    assert export == uv_mod.export_command("uv", group, pylock)
    assert install == uv_mod.install_command("uv", pylock, "t")
    assert pylock.name == "pylock.cortex.toml"
    assert pylock.parent.name.startswith(".cortex-pylock-")
    for kwargs in (export_kw, install_kw):
        assert kwargs == {"capture_output": True, "text": True, "env": kwargs["env"]}
        assert "UV_FROZEN" not in kwargs["env"]
        assert kwargs["env"]["PATH"] == uv_mod.os.environ["PATH"]
