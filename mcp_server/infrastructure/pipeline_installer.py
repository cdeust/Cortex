"""Silent installer for the upstream ai-automatised-pipeline binary.

Bootstraps a fresh user machine. Strategy: prebuilt binary fast-path
(GitHub Releases, hash-verified, ~10 s) → falls back to source build
(rustup → git clone → cargo build, ~5–8 min). Idempotent. All
subprocess output is captured. File-locked against concurrent runs.

Opt-out env vars: CORTEX_AUTO_INSTALL_PIPELINE=0 (skip all),
CORTEX_AUTO_INSTALL_RUST=0 (skip rustup), CORTEX_PIPELINE_GIT_URL=<url>
(fork override), CORTEX_DISABLE_PREBUILT=1 (skip release fast-path),
CORTEX_RUSTUP_PIN_HASH=0 (skip rustup hash verification).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from mcp_server.infrastructure.pipeline_discovery import (
    _INSTALL_BIN_DIR,
    _INSTALL_SRC_DIR,
    _INSTALL_SYMLINK,
)
from mcp_server.infrastructure.pipeline_install_lock import (
    InstallLockBusy,
    install_lock,
)
from mcp_server.infrastructure.pipeline_install_release import try_install_prebuilt
from mcp_server.infrastructure.pipeline_install_rust import (
    install_rust_toolchain,
    resolve_cargo,
    _CARGO_HOME_BIN,
)
from mcp_server.infrastructure.pipeline_installer_common import (
    _rmtree_quiet,
    _run_quiet,
)

logger = logging.getLogger(__name__)

_DEFAULT_GIT_URL = "https://github.com/cdeust/automatised-pipeline.git"
_BUILT_BINARY_REL = "target/release/ai-architect-mcp"
_DISABLE_ENV = "CORTEX_AUTO_INSTALL_PIPELINE"

# Minimum acceptable size for a successfully-built ai-architect-mcp
# binary. The release build is multi-MB; anything below this threshold
# is a corrupted or 0-byte file (disk full, killed compiler, etc.).
_MIN_BINARY_BYTES = 1_024 * 1_024

# CI signals — default-skip the install in CI (5–8 min cold cost).
# Users opt in with CORTEX_AUTO_INSTALL_PIPELINE=1.
_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS")


def _binary_is_usable(path: Path) -> bool:
    """Tighter than ``is_file()``: exists, executable, plausible size."""
    try:
        return (
            path.is_file()
            and os.access(path, os.X_OK)
            and path.stat().st_size >= _MIN_BINARY_BYTES
        )
    except OSError:
        return False


def _is_ci_environment() -> bool:
    """True under a recognised CI provider AND not explicitly opted in."""
    if os.environ.get(_DISABLE_ENV, "").strip() in {"1", "true", "yes"}:
        return False
    return any(os.environ.get(name) for name in _CI_ENV_VARS)


def install_pipeline(force_rebuild: bool = False, git_url: Optional[str] = None) -> dict:
    """Best-effort silent install of the upstream pipeline binary.

    Returns audit dict with one of these actions:
      already_installed | installed | installed_prebuilt
      missing_toolchain | clone_failed | build_failed | symlink_failed
      home_readonly | disabled | ci_skipped | install_in_progress
    """
    if os.environ.get(_DISABLE_ENV, "").strip() in {"0", "false", "no"}:
        return {"action": "disabled"}

    if _is_ci_environment():
        return {"action": "ci_skipped"}

    if not force_rebuild and _binary_is_usable(_INSTALL_SYMLINK):
        return {"action": "already_installed", "binary": str(_INSTALL_SYMLINK)}

    try:
        with install_lock():
            return _install_locked(force_rebuild, git_url)
    except InstallLockBusy as exc:
        return {"action": "install_in_progress", "detail": str(exc)}


def _install_locked(force_rebuild: bool, git_url: Optional[str]) -> dict:
    """Install body, executed under the exclusive file-lock."""
    # Re-check usability under the lock — another process may have
    # finished between our outer check and lock acquisition.
    if not force_rebuild and _binary_is_usable(_INSTALL_SYMLINK):
        return {"action": "already_installed", "binary": str(_INSTALL_SYMLINK)}

    # Fast path: prebuilt release binary. Always-non-fatal — failure
    # falls through to the source-build path below.
    if not force_rebuild:
        prebuilt = try_install_prebuilt(_INSTALL_SYMLINK)
        if prebuilt.get("action") == "installed_prebuilt" and _binary_is_usable(_INSTALL_SYMLINK):
            return prebuilt

    cargo = resolve_cargo()
    if not cargo:
        rust_result = install_rust_toolchain()
        if rust_result.get("action") in {"rust_installed", "rust_already_present"}:
            cargo = rust_result.get("cargo")
        else:
            return {
                "action": "missing_toolchain",
                "missing": ["cargo"],
                "rust_install_action": rust_result.get("action"),
                "detail": rust_result.get("detail"),
                "hash_pin_status": rust_result.get("hash_pin_status"),
            }

    git = shutil.which("git")
    if not git:
        return {"action": "missing_toolchain", "missing": ["git"]}

    src = _INSTALL_SRC_DIR
    try:
        src.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"action": "home_readonly", "detail": str(exc)}
    url = git_url or os.environ.get("CORTEX_PIPELINE_GIT_URL") or _DEFAULT_GIT_URL

    clone_result = _ensure_source(src, url, git, force_rebuild)
    if clone_result is not None:
        return clone_result

    binary = src / _BUILT_BINARY_REL
    if force_rebuild or not _binary_is_usable(binary):
        env = {**os.environ, "PATH": f"{_CARGO_HOME_BIN}:{os.environ.get('PATH', '')}"}
        rc, tail = _run_quiet(
            [cargo, "build", "--release", "--bin", "ai-architect-mcp"],
            cwd=str(src),
            env=env,
            timeout=1800,
        )
        if rc != 0 or not _binary_is_usable(binary):
            return {"action": "build_failed", "detail": tail}

    return _swap_symlink(binary)


def _ensure_source(src: Path, url: str, git: str, force_rebuild: bool) -> Optional[dict]:
    """Clone or refresh the source tree. Return None on success, or
    a structured failure dict."""
    # Validate any existing checkout. A half-cloned dir leaves
    # src.exists() True with no Cargo.toml — re-clone is the only
    # safe recovery.
    if src.exists() and not (src / "Cargo.toml").is_file():
        try:
            _rmtree_quiet(src)
        except OSError as exc:
            return {"action": "clone_failed", "detail": f"stale partial src cleanup: {exc}"}

    if not src.exists():
        # Clone into a .partial sibling, atomic-rename on success.
        partial = src.with_name(src.name + ".partial")
        if partial.exists():
            _rmtree_quiet(partial)
        rc, tail = _run_quiet([git, "clone", "--depth=1", url, str(partial)], timeout=1800)
        if rc != 0 or not (partial / "Cargo.toml").is_file():
            _rmtree_quiet(partial)
            return {"action": "clone_failed", "detail": tail}
        os.rename(str(partial), str(src))
    elif force_rebuild:
        _run_quiet([git, "-C", str(src), "fetch", "--depth=1", "origin", "HEAD"])
        _run_quiet([git, "-C", str(src), "reset", "--hard", "FETCH_HEAD"])
    return None


def _swap_symlink(binary: Path) -> dict:
    """Atomic symlink swap (link-to-temp + os.replace)."""
    try:
        _INSTALL_BIN_DIR.mkdir(parents=True, exist_ok=True)
        tmp_link = _INSTALL_SYMLINK.with_name(_INSTALL_SYMLINK.name + ".new")
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        tmp_link.symlink_to(binary)
        os.replace(str(tmp_link), str(_INSTALL_SYMLINK))
    except Exception as exc:
        return {"action": "symlink_failed", "detail": str(exc)}
    return {"action": "installed", "binary": str(_INSTALL_SYMLINK)}
