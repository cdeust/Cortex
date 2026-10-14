"""scripts/launcher_python.py: below Python 3.10 the launcher re-runs itself on
the pinned CPython it installs, or stops with uv's own error.

On a Mac with only the Command Line Tools, ``python3`` is 3.9.6 and the
locked sets cannot install for it (measured 2026-10-14: "The requested
interpreter resolved to Python 3.9.6, which is incompatible with the
pylock.toml's Python requirement: >=3.10").

source: ADR-1104
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def py_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_python", REPO_ROOT / "scripts" / "launcher_python.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def execs(py_mod, monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(
        py_mod.os, "execv", lambda path, argv: calls.append((path, argv))
    )
    monkeypatch.setattr(py_mod.sys, "platform", "darwin")
    return calls


def test_a_supported_python_is_used_as_is(py_mod, execs, monkeypatch):
    monkeypatch.setattr(py_mod, "provide", lambda d: pytest.fail("provided"))
    py_mod.ensure_supported("/data/deps", "/plugin/scripts/launcher.py")
    assert execs == []


def test_an_old_python_reexecs_on_the_installed_one(py_mod, execs, monkeypatch):
    monkeypatch.setattr(py_mod, "supported", lambda: False)
    monkeypatch.setattr(py_mod, "installed", lambda d: "/data/python/bin/python3.12")
    monkeypatch.setattr(py_mod.sys, "argv", ["launcher.py", "mcp_server"])
    py_mod.ensure_supported("/data/deps", "/plugin/scripts/launcher.py")
    assert execs == [
        (
            "/data/python/bin/python3.12",
            [
                "/data/python/bin/python3.12",
                "/plugin/scripts/launcher.py",
                "mcp_server",
            ],
        )
    ]


def test_an_old_python_installs_the_pinned_one_first(py_mod, execs, monkeypatch):
    monkeypatch.setattr(py_mod, "supported", lambda: False)
    monkeypatch.setattr(py_mod, "installed", lambda d: None)
    monkeypatch.setattr(py_mod, "provide", lambda d: "/data/python/bin/python3.12")
    py_mod.ensure_supported("/data/deps", "launcher.py")
    assert execs[0][0] == "/data/python/bin/python3.12"


def test_no_python_to_install_is_a_loud_stop(py_mod, execs, monkeypatch, capsys):
    monkeypatch.setattr(py_mod, "supported", lambda: False)
    monkeypatch.setattr(py_mod, "installed", lambda d: None)

    def offline(_deps_dir):
        raise py_mod.InterpreterError("error: Failed to download cpython-3.12.13")

    monkeypatch.setattr(py_mod, "provide", offline)
    with pytest.raises(SystemExit) as stopped:
        py_mod.ensure_supported("/data/deps", "launcher.py")
    assert stopped.value.code == 1
    err = capsys.readouterr().err
    assert ">= 3.10" in err and py_mod.MANAGED_PYTHON in err
    assert "Failed to download cpython-3.12.13" in err
    assert execs == []


def test_the_managed_python_lives_in_plugin_data(py_mod):
    assert py_mod.managed_dir("/data/deps") == Path("/data/python")


def test_installed_reads_the_record_provide_wrote(py_mod, tmp_path, monkeypatch):
    deps_dir = str(tmp_path / "deps")
    assert py_mod.installed(deps_dir) is None
    python = tmp_path / "python" / "cpython" / "bin" / "python3.12"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)

    class _Done:
        returncode, stdout, stderr = 0, f"{python}\n", ""

    monkeypatch.setattr(py_mod._uv, "locate", lambda d: "uv")
    monkeypatch.setattr(py_mod.subprocess, "run", lambda argv, **kw: _Done())
    assert py_mod.provide(deps_dir) == str(python)
    monkeypatch.setattr(py_mod.subprocess, "run", lambda *a, **k: pytest.fail("ran uv"))
    assert py_mod.installed(deps_dir) == str(python)
    python.unlink()
    assert (
        py_mod.installed(deps_dir) is None
    )  # a removed interpreter is not "installed"


def test_provide_runs_the_pinned_uv_with_a_private_install_dir(
    py_mod, monkeypatch, tmp_path
):
    seen: list = []

    class _Done:
        returncode, stdout, stderr = 0, "/data/python/cpython/bin/python3.12\n", ""

    def run(argv, **kwargs):
        seen.append((argv, kwargs["env"]))
        return _Done()

    monkeypatch.setattr(py_mod._uv, "locate", lambda d: "/data/deps.uv/bin/uv")
    monkeypatch.setattr(py_mod.subprocess, "run", run)
    monkeypatch.setattr(py_mod, "_record", lambda d: tmp_path / "interpreter")
    assert py_mod.provide("/data/deps") == "/data/python/cpython/bin/python3.12"
    argv, env = seen[0]
    assert argv == [
        "/data/deps.uv/bin/uv", "python", "find", py_mod.MANAGED_PYTHON,
        "--managed-python",
    ]  # fmt: skip
    assert env["UV_PYTHON_INSTALL_DIR"] == str(Path("/data/python"))
    assert env["UV_NO_CACHE"] == "1"
