"""scripts/launcher_uv.py: the locked-set export and install commands.

source: ADR-1092"""

from __future__ import annotations

import hashlib
import importlib.util
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


def test_install_feeds_the_exported_pylock_to_uv_pip(
    uv_mod, monkeypatch, uv_runs, tmp_path
):
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda cmd, **k: uv_runs.append((cmd, k)) or _done()
    )
    group = ("--only-group", "g")
    target = tmp_path / "t"
    target.mkdir()
    (target / ".lock").write_text("")  # what uv leaves in its --target
    (target / "kept").write_text("")
    assert uv_mod.install_locked_set("deps", group, str(target)).returncode == 0
    assert [entry.name for entry in target.iterdir()] == ["kept"]
    (export, export_kw), (install, install_kw) = uv_runs[1:]
    pylock = Path(export[export.index("--output-file") + 1])
    assert uv_runs[0] == ["deps"]
    assert export == uv_mod.export_command("uv", group, pylock)
    assert install == uv_mod.install_command("uv", pylock, str(target))
    assert pylock.name == "pylock.cortex.toml"
    assert pylock.parent.name.startswith(".cortex-pylock-")
    for kwargs in (export_kw, install_kw):
        assert kwargs == {"capture_output": True, "text": True, "env": kwargs["env"]}
        assert "UV_FROZEN" not in kwargs["env"]
        assert kwargs["env"]["PATH"] == uv_mod.os.environ["PATH"]


def _exporting(uv_runs, body: bytes, returncode: int = 0, **streams):
    def run(cmd, **kwargs):
        uv_runs.append((cmd, kwargs))
        Path(cmd[cmd.index("--output-file") + 1]).write_bytes(body)
        return _done(returncode, **streams)

    return run


def test_set_digest_is_the_sha256_of_the_export_without_its_header(
    uv_mod, monkeypatch, uv_runs
):
    body = b"# uv export --output-file /somewhere/else\nlock-version = 1\n#x\nb = 2\n"
    monkeypatch.setattr(uv_mod.subprocess, "run", _exporting(uv_runs, body))
    group = ("--only-group", "g")
    digest = uv_mod.locked_set_digest("deps", group)
    assert digest == hashlib.sha256(b"lock-version = 1\nb = 2").hexdigest()
    (export, kwargs) = uv_runs[1]
    pylock = Path(export[export.index("--output-file") + 1])
    assert uv_runs[0] == ["deps"] and len(uv_runs) == 2
    assert export == uv_mod.export_command("uv", group, pylock)
    assert pylock.name == "pylock.cortex.toml"
    assert pylock.parent.name.startswith(".cortex-pylock-")
    assert kwargs == {"capture_output": True, "text": True, "env": kwargs["env"]}
    assert "UV_FROZEN" not in kwargs["env"]
    assert kwargs["env"]["PATH"] == uv_mod.os.environ["PATH"]


@pytest.mark.parametrize(
    ("streams", "message"),
    [
        ({"stderr": " lock is stale \n", "stdout": "ignored"}, "lock is stale"),
        ({"stdout": " said on stdout \n"}, "said on stdout"),
    ],
)
def test_set_digest_raises_uvs_own_error_when_the_export_fails(
    uv_mod, monkeypatch, uv_runs, streams, message
):
    monkeypatch.setattr(
        uv_mod.subprocess, "run", _exporting(uv_runs, b"partial", 2, **streams)
    )
    with pytest.raises(uv_mod.LockedSetError) as raised:
        uv_mod.locked_set_digest("deps", ("--only-group", "g"))
    assert str(raised.value) == message


@pytest.fixture
def install_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_deps_install", REPO_ROOT / "scripts/launcher_deps_install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_reads_the_set_digest_through_launcher_uv(install_mod, monkeypatch):
    asked = []
    monkeypatch.setattr(
        install_mod._uv, "locked_set_digest", lambda *a: asked.append(a) or "abc"
    )
    assert install_mod.locked_set_digest("deps", ("--only-group", "g")) == "abc"
    assert asked == [("deps", ("--only-group", "g"))]


@pytest.mark.parametrize("error", ["UvUnavailableError", "LockedSetError", "OSError"])
def test_installer_prints_why_a_set_digest_is_unavailable(
    install_mod, monkeypatch, capsys, error
):
    kind = getattr(install_mod._uv, error, OSError)

    def refuse(*_a):
        raise kind("no uv here")

    monkeypatch.setattr(install_mod._uv, "locked_set_digest", refuse)
    assert install_mod.locked_set_digest("deps", ()) is None
    expected = "[cortex-launcher] dependency install failed: no uv here\n"
    assert capsys.readouterr().err == expected
