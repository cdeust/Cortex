"""scripts/launcher_uv.py: pinned uv discovery, bootstrap and locked-set install.

source: ADR-1092"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


@pytest.fixture
def uv_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_uv", SCRIPTS / "launcher_uv.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _done(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _fake_uv_site(command: list[str]) -> None:
    site = Path(command[command.index("--target") + 1])
    (site / "bin").mkdir(parents=True)
    (site / "bin" / "uv").write_text("binary")


def test_hashes_are_distinct_sha256_digests(uv_mod):
    assert len(set(uv_mod.UV_HASHES)) == len(uv_mod.UV_HASHES) == 19
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in uv_mod.UV_HASHES)


def test_bootstrap_command_is_binary_only_and_hash_checked(uv_mod, monkeypatch):
    monkeypatch.setattr(uv_mod._pip, "pip_entry", lambda: ["py", "-m", "pip"])
    assert uv_mod.bootstrap_command(Path("t"), Path("r.txt")) == [
        "py", "-m", "pip", "install", "-q", "--disable-pip-version-check",
        "--index-url", "https://pypi.org/simple/", "--only-binary=:all:",
        "--no-deps", "--require-hashes", "--target", "t", "-r", "r.txt",
    ]  # fmt: skip


def test_locate_prefers_path_uv_only_at_the_pinned_version(uv_mod, monkeypatch):
    monkeypatch.setattr(uv_mod.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(uv_mod, "_version_of", lambda _b: uv_mod.UV_VERSION)
    assert uv_mod.locate("deps") == "/usr/bin/uv"
    monkeypatch.setattr(uv_mod, "_version_of", lambda _b: "0.1.0")
    monkeypatch.setattr(uv_mod, "_bootstrap", lambda d: Path(f"{d}-boot/uv"))
    assert uv_mod.locate("deps") == str(Path("deps-boot/uv"))


def test_locate_reuses_an_already_bootstrapped_copy(uv_mod, monkeypatch, tmp_path):
    deps = str(tmp_path / "deps")
    binary = uv_mod.private_dir(deps) / "bin" / "uv"
    binary.parent.mkdir(parents=True)
    binary.write_text("binary")
    monkeypatch.setattr(uv_mod.shutil, "which", lambda _name: None)
    monkeypatch.setattr(uv_mod, "_bootstrap", lambda _d: pytest.fail("bootstrapped"))
    assert uv_mod.locate(deps) == str(binary)
    assert uv_mod.private_dir(deps).name == f"deps.uv-{uv_mod.UV_VERSION}"


def test_version_of_reads_uv_version_output(uv_mod, monkeypatch):
    out = _done(stdout="uv 0.11.3 (45da18ac3 2026-04-01 aarch64-apple-darwin)\n")
    monkeypatch.setattr(uv_mod.subprocess, "run", lambda *_a, **_k: out)
    assert uv_mod._version_of("uv") == "0.11.3"
    monkeypatch.setattr(uv_mod.subprocess, "run", lambda *_a, **_k: _done(1))
    assert uv_mod._version_of("uv") is None


def test_bootstrap_installs_the_pinned_wheel_beside_deps(uv_mod, monkeypatch, tmp_path):
    deps = str(tmp_path / "deps")
    seen = {}

    def fake_install(command, environment):
        seen["requirement"] = Path(command[-1]).read_text()
        seen["config"] = environment["PIP_CONFIG_FILE"]
        _fake_uv_site(command)
        return _done()

    monkeypatch.setattr(uv_mod._pip, "run_install", fake_install)
    binary = uv_mod._bootstrap(deps)
    assert binary == uv_mod.private_dir(deps) / "bin" / "uv"
    assert seen["requirement"].startswith(f"uv=={uv_mod.UV_VERSION} --hash=sha256:")
    assert seen["requirement"].count("--hash=sha256:") == 19
    assert [p.name for p in tmp_path.iterdir()] == [f"deps.uv-{uv_mod.UV_VERSION}"]


def test_bootstrap_replaces_an_interrupted_copy_without_binary(
    uv_mod, monkeypatch, tmp_path
):
    deps = str(tmp_path / "deps")
    (uv_mod.private_dir(deps) / "uv").mkdir(parents=True)
    monkeypatch.setattr(
        uv_mod._pip,
        "run_install",
        lambda command, _env: _fake_uv_site(command) or _done(),
    )
    assert uv_mod._bootstrap(deps) == uv_mod.private_dir(deps) / "bin" / "uv"


def test_bootstrap_failure_is_loud_and_leaves_nothing(uv_mod, monkeypatch, tmp_path):
    failed = _done(1, stderr="ERROR: network unreachable")
    monkeypatch.setattr(uv_mod._pip, "run_install", lambda *_a: failed)
    with pytest.raises(uv_mod.UvUnavailableError) as raised:
        uv_mod._bootstrap(str(tmp_path / "deps"))
    assert "network unreachable" in str(raised.value)
    assert f"Install uv {uv_mod.UV_VERSION} yourself" in str(raised.value)
    assert list(tmp_path.iterdir()) == []


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


def test_environment_drops_settings_that_weaken_the_install(uv_mod, monkeypatch):
    for name in ("UV_NO_VERIFY_HASHES", "UV_LOCKED", "UV_FROZEN", "UV_PYTHON"):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("UV_CACHE_DIR", "kept")
    env = uv_mod.environment()
    assert env["UV_CACHE_DIR"] == "kept"
    assert not {"UV_NO_VERIFY_HASHES", "UV_LOCKED", "UV_FROZEN", "UV_PYTHON"} & set(env)


def test_install_stops_at_a_failed_export(uv_mod, monkeypatch):
    runs = []
    monkeypatch.setattr(uv_mod, "locate", lambda _d: "uv")
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda cmd, **_k: runs.append(cmd) or _done(2)
    )
    result = uv_mod.install_locked_set("deps", ("--only-group", "g"), "scratch")
    assert result.returncode == 2
    assert [cmd[1] for cmd in runs] == ["export"]


def test_install_feeds_the_exported_pylock_to_uv_pip(uv_mod, monkeypatch):
    runs = []
    monkeypatch.setattr(uv_mod, "locate", lambda _d: "uv")
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda cmd, **_k: runs.append(cmd) or _done()
    )
    assert uv_mod.install_locked_set("deps", ("--only-group", "g"), "t").returncode == 0
    exported = runs[0][runs[0].index("--output-file") + 1]
    assert runs[1][-1] == exported
    assert Path(exported).name == "pylock.cortex.toml"
