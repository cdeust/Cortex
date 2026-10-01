"""scripts/launcher_uv.py: pinned uv discovery and bootstrap.

source: ADR-1092"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests_py.scripts._launcher_uv_fixture import done as _done
from tests_py.scripts._launcher_uv_fixture import fake_uv_site as _fake_uv_site


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
    asked = []
    monkeypatch.setattr(
        uv_mod.shutil, "which", lambda name: asked.append(name) or "/usr/bin/uv"
    )
    probed = []
    version = {"value": uv_mod.UV_VERSION}
    monkeypatch.setattr(
        uv_mod, "_version_of", lambda b: probed.append(b) or version["value"]
    )
    assert uv_mod.locate("deps") == "/usr/bin/uv"
    assert asked == ["uv"] and probed == ["/usr/bin/uv"]
    version["value"] = "0.1.0"
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


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            _done(stdout="uv 0.11.3 (45da18ac3 2026-04-01 aarch64-apple-darwin)\n"),
            "0.11.3",
        ),
        (_done(stdout="uv 0.11.3"), "0.11.3"),
        (_done(1, stdout="uv 0.11.3"), None),
        (_done(stdout="uv"), None),
    ],
)
def test_version_of_reads_uv_version_output(uv_mod, monkeypatch, result, expected):
    calls = []
    monkeypatch.setattr(
        uv_mod.subprocess, "run", lambda *a, **k: calls.append((a, k)) or result
    )
    assert uv_mod._version_of("/x/uv") == expected
    assert calls == [
        ((["/x/uv", "--version"],), {"capture_output": True, "text": True})
    ]


def test_version_of_is_none_when_the_binary_cannot_run(uv_mod, monkeypatch):
    def unrunnable(*_a, **_k):
        raise PermissionError("not executable")

    monkeypatch.setattr(uv_mod.subprocess, "run", unrunnable)
    assert uv_mod._version_of("/x/uv") is None


@pytest.mark.parametrize("relative", ["bin/uv", "bin/uv.exe", "Scripts/uv.exe"])
def test_binary_is_found_in_every_wheel_scripts_layout(uv_mod, tmp_path, relative):
    (tmp_path / relative).parent.mkdir(parents=True)
    (tmp_path / relative).write_text("binary")
    assert uv_mod._binary_in(tmp_path) == tmp_path / relative
    assert uv_mod._binary_in(tmp_path / "absent") is None


@pytest.fixture
def fs_calls(uv_mod, monkeypatch) -> dict[str, list]:
    """Record rmtree/os.replace calls while still performing them."""
    calls: dict[str, list] = {"rmtree": [], "replace": []}
    real_rmtree, real_replace = uv_mod.shutil.rmtree, uv_mod.os.replace

    def rmtree(path, **kwargs):
        calls["rmtree"].append(kwargs)
        return real_rmtree(path, **kwargs)

    def replace(src, dst):
        calls["replace"].append((Path(src).name, Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(uv_mod.shutil, "rmtree", rmtree)
    monkeypatch.setattr(uv_mod.os, "replace", replace)
    return calls


def test_bootstrap_installs_the_pinned_wheel_beside_deps(
    uv_mod, monkeypatch, tmp_path, fs_calls, capsys
):
    deps = str(tmp_path / "not-yet" / "deps")
    seen = {}

    def fake_install(command, environment):
        seen["requirement"] = Path(command[-1])
        seen["target"] = Path(command[command.index("--target") + 1]).name
        seen["config"] = environment["PIP_CONFIG_FILE"]
        _fake_uv_site(command)
        return _done()

    monkeypatch.setattr(uv_mod._pip, "run_install", fake_install)
    binary = uv_mod._bootstrap(deps)
    target = uv_mod.private_dir(deps)
    assert binary == target / "bin" / "uv"
    assert seen["requirement"].name == "uv-requirement.txt"
    assert seen["target"] == "site" and seen["config"] == uv_mod.os.devnull
    assert fs_calls["replace"] == [("site", target)]
    assert all(kw == {"ignore_errors": True} for kw in fs_calls["rmtree"])
    assert [p.name for p in (tmp_path / "not-yet").iterdir()] == [target.name]
    expected = f"[cortex-launcher] installing uv {uv_mod.UV_VERSION} into {target}\n"
    assert capsys.readouterr().err == expected
    assert (target / "bin" / "uv").read_text() == "binary"


def test_bootstrap_writes_the_exact_hash_pinned_requirement(
    uv_mod, monkeypatch, tmp_path
):
    written = {}

    def fake_install(command, _env):
        written["text"] = Path(command[-1]).read_text(encoding="ascii")
        _fake_uv_site(command)
        return _done()

    monkeypatch.setattr(uv_mod._pip, "run_install", fake_install)
    uv_mod._bootstrap(str(tmp_path / "deps"))
    hashes = " ".join(f"--hash=sha256:{h}" for h in uv_mod.UV_HASHES)
    assert written["text"] == f"uv=={uv_mod.UV_VERSION} {hashes}\n"


def test_bootstrap_replaces_an_interrupted_copy_without_binary(
    uv_mod, monkeypatch, tmp_path, fs_calls
):
    deps = str(tmp_path / "deps")
    (uv_mod.private_dir(deps) / "uv").mkdir(parents=True)
    monkeypatch.setattr(
        uv_mod._pip,
        "run_install",
        lambda command, _env: _fake_uv_site(command) or _done(),
    )
    assert uv_mod._bootstrap(deps) == uv_mod.private_dir(deps) / "bin" / "uv"
    assert all(kw == {"ignore_errors": True} for kw in fs_calls["rmtree"])


def test_bootstrap_keeps_a_concurrent_winners_copy(uv_mod, monkeypatch, tmp_path):
    deps = str(tmp_path / "deps")
    winner = uv_mod.private_dir(deps) / "bin" / "uv"
    winner.parent.mkdir(parents=True)
    winner.write_text("winner")
    monkeypatch.setattr(
        uv_mod._pip,
        "run_install",
        lambda command, _env: _fake_uv_site(command) or _done(),
    )
    assert uv_mod._bootstrap(deps) == winner
    assert winner.read_text() == "winner"


def test_bootstrap_without_a_binary_in_the_wheel_is_an_error(
    uv_mod, monkeypatch, tmp_path
):
    def empty_site(command, _env):
        Path(command[command.index("--target") + 1]).mkdir(parents=True)
        return _done()

    monkeypatch.setattr(uv_mod._pip, "run_install", empty_site)
    deps = str(tmp_path / "deps")
    with pytest.raises(uv_mod.UvUnavailableError) as raised:
        uv_mod._bootstrap(deps)
    target = uv_mod.private_dir(deps)
    assert (
        str(raised.value)
        == f"uv {uv_mod.UV_VERSION} installed into {target} has no binary"
    )


def test_bootstrap_failure_is_loud_and_leaves_nothing(
    uv_mod, monkeypatch, tmp_path, fs_calls
):
    failed = _done(1, stdout="ignored", stderr="@" + "E" * 1500)
    monkeypatch.setattr(uv_mod._pip, "run_install", lambda *_a: failed)
    with pytest.raises(uv_mod.UvUnavailableError) as raised:
        uv_mod._bootstrap(str(tmp_path / "deps"))
    assert str(raised.value) == (
        f"could not install uv {uv_mod.UV_VERSION} from PyPI with pip: {'E' * 1500}\n"
        f"Install uv {uv_mod.UV_VERSION} yourself (https://docs.astral.sh/uv/) "
        "and put it on PATH, then restart."
    )
    assert list(tmp_path.iterdir()) == []
    assert all(kw == {"ignore_errors": True} for kw in fs_calls["rmtree"])


def test_bootstrap_failure_reports_stdout_when_stderr_is_empty(
    uv_mod, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        uv_mod._pip, "run_install", lambda *_a: _done(1, stdout="pip said no")
    )
    with pytest.raises(uv_mod.UvUnavailableError, match="pip said no"):
        uv_mod._bootstrap(str(tmp_path / "deps"))
