"""Locate or bootstrap the pinned uv, then install a uv.lock set — stdlib only.

uv.lock is the only dependency source. ``uv export`` turns one set of it
into a ``pylock.toml`` whose every wheel carries its exact URL and sha256,
and ``uv pip install --target`` installs that file, verifying each hash.
When no uv at the pinned version is on PATH, pip installs that uv wheel,
hash-checked, into a private directory next to ``deps_dir``.

source: ADR-1092"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import launcher_pip as _pip

PROJECT_ROOT = Path(__file__).resolve().parent.parent

UV_VERSION = "0.11.3"  # source: ADR-1092

# Every distribution PyPI serves for uv 0.11.3; pip picks this host's wheel
# (source: ADR-1092).
UV_HASHES = (
    "088165b9eed981d2c2a58566cc75dd052d613e47c65e2416842d07308f793a6f",
    "089b9d338a64463956b6fee456f03f73c9a916479bdb29009600781dc1e1d2a7",
    "0fde893b5ab9f6997fe357138e794bac09d144328052519fbbe2e6f72145e457",
    "3b1fe09d5e1d8e19459cd28d7825a3b66ef147b98328345bad6e17b87c4fea48",
    "3ff461335888336467402cc5cb792c911df95dd0b52e369182cfa4c902bb21f4",
    "45006bcd9e8718248a23ab81448a5beb46a72a9dd508e3212d6f3b8c63aeb88a",
    "55ba578752f29a3f2b22879b22a162edad1454e3216f3ca4694fdbd4093a6822",
    "6708827ecb846d00c5512a7e4dc751c2e27b92e9bd55a0be390561ac68930c32",
    "68fda574f2e5e7536a2b747dcea88329a71aad7222317e8f4717d0af8f99fbd4",
    "6a6fcaf1fec28bbbdf0dfc5a0a6e34be4cea08c6287334b08c24cf187300f20d",
    "71f5d0b9e73daa5d8a7e2db3fa2e22a4537d24bb4fe78130db797280280d4edc",
    "794aae3bab141eafbe37c51dc5dd0139658a755a6fa9cc74d2dbd7c71dcc4826",
    "8df030ea7563e99c09854e1bc82ab743dfa2d0ba18976e6861979cb40d04dba7",
    "92ffc4d521ab2c4738ef05d8ef26f2750e26d31f3ad5611cdfefc52445be9ace",
    "a62e29277efd39c35caf4a0fe739c4ebeb14d4ce4f02271f3f74271d608061ff",
    "d2b3b0fa1693880ca354755c216ae1c65dd938a4f1a24374d0c3f4b9538e0ee6",
    "deb533e780e8181e0859c68c84f546620072cd1bd827b38058cb86ebfba9bb7d",
    "ebccdcdebd2b288925f0f7c18c39705dc783175952eacaf94912b01d3b381b86",
    "ef0ae8ee2988928092616401ec7f473612b8e9589fe1567452c45dbc56840f85",
)

# Settings that would weaken or contradict the locked install if inherited
# (source: ADR-1092).
_UV_ENV_DROPPED = (
    "UV_NO_VERIFY_HASHES",
    "UV_LOCKED",
    "UV_FROZEN",
    "UV_PYTHON",
    "UV_PROJECT_ENVIRONMENT",
)


class UvUnavailableError(RuntimeError):
    """The pinned uv is neither on PATH nor installable; the message says why."""


def private_dir(deps_dir: str) -> Path:
    """Where the bootstrapped uv lives: beside ``deps_dir``, one per version."""
    return Path(f"{deps_dir}.uv-{UV_VERSION}")


def _binary_in(directory: Path) -> Path | None:
    for relative in ("bin/uv", "bin/uv.exe", "Scripts/uv.exe"):
        candidate = directory / relative
        if candidate.is_file():
            return candidate
    return None


def _version_of(binary: str) -> str | None:
    try:
        process = subprocess.run([binary, "--version"], capture_output=True, text=True)
    except OSError:
        return None
    fields = process.stdout.split()
    return fields[1] if process.returncode == 0 and len(fields) > 1 else None


def bootstrap_command(target: Path, requirement: Path) -> list[str]:
    """pip, binary-only and hash-checked, installing the pinned uv wheel."""
    return [
        *_pip.pip_entry(),
        "install",
        "-q",
        "--disable-pip-version-check",
        "--index-url",
        "https://pypi.org/simple/",
        "--only-binary=:all:",
        "--no-deps",
        "--require-hashes",
        "--target",
        str(target),
        "-r",
        str(requirement),
    ]


def _bootstrap(deps_dir: str) -> Path:
    target = private_dir(deps_dir)
    scratch = Path(f"{target}.tmp-{os.getpid()}")
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    requirement = scratch / "uv-requirement.txt"
    hashes = " ".join(f"--hash=sha256:{digest}" for digest in UV_HASHES)
    requirement.write_text(f"uv=={UV_VERSION} {hashes}\n", encoding="utf-8")
    print(
        f"[cortex-launcher] installing uv {UV_VERSION} into {target}", file=sys.stderr
    )
    process = _pip.run_install(
        bootstrap_command(scratch / "site", requirement), _pip.clean_environment()
    )
    if process.returncode:
        shutil.rmtree(scratch, ignore_errors=True)
        raise UvUnavailableError(
            f"could not install uv {UV_VERSION} from PyPI with pip: "
            f"{(process.stderr or process.stdout).strip()[-1500:]}\n"
            f"Install uv {UV_VERSION} yourself (https://docs.astral.sh/uv/) "
            "and put it on PATH, then restart."
        )
    if target.exists() and _binary_in(target) is None:
        shutil.rmtree(target, ignore_errors=True)  # an interrupted earlier copy
    try:
        os.replace(scratch / "site", target)
    except OSError:
        if _binary_in(target) is None:  # not a concurrent winner: a real failure
            raise
    shutil.rmtree(scratch, ignore_errors=True)
    binary = _binary_in(target)
    if binary is None:
        raise UvUnavailableError(
            f"uv {UV_VERSION} installed into {target} has no binary"
        )
    return binary


def locate(deps_dir: str) -> str:
    """The uv to run: PATH's at exactly ``UV_VERSION``, else the private copy."""
    on_path = shutil.which("uv")
    if on_path and _version_of(on_path) == UV_VERSION:
        return on_path
    private = _binary_in(private_dir(deps_dir))
    if private is not None:
        return str(private)
    return str(_bootstrap(deps_dir))


def environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in _UV_ENV_DROPPED:
        env.pop(name, None)
    return env


def export_command(uv: str, set_args: tuple[str, ...], output: Path) -> list[str]:
    """``uv export`` of one locked set, as a pylock file uv can install from."""
    return [
        uv,
        "export",
        "--quiet",
        "--frozen",
        "--no-config",
        "--project",
        str(PROJECT_ROOT),
        "--no-emit-project",
        "--no-default-groups",
        *set_args,
        "--format",
        "pylock.toml",
        "--output-file",
        str(output),
    ]


def install_command(uv: str, pylock: Path, target: str) -> list[str]:
    """Install a pylock into ``target`` for THIS interpreter, hashes verified."""
    return [
        uv,
        "pip",
        "install",
        "--quiet",
        "--no-config",
        "--preview-features",
        "pylock",
        "--python",
        sys.executable,
        "--require-hashes",
        "--target",
        target,
        "-r",
        str(pylock),
    ]


def install_locked_set(
    deps_dir: str, set_args: tuple[str, ...], target: str
) -> subprocess.CompletedProcess[str]:
    """Export ``set_args`` from uv.lock and install it into ``target``.

    Raises ``UvUnavailableError`` when uv cannot be found or installed; an export
    or install failure is returned as the failed process, never retried.
    """
    uv = locate(deps_dir)
    env = environment()
    with tempfile.TemporaryDirectory(prefix=".cortex-pylock-") as temporary:
        pylock = Path(temporary) / "pylock.cortex.toml"
        exported = subprocess.run(
            export_command(uv, set_args, pylock),
            capture_output=True,
            text=True,
            env=env,
        )
        if exported.returncode:
            return exported
        return subprocess.run(
            install_command(uv, pylock, target),
            capture_output=True,
            text=True,
            env=env,
        )
