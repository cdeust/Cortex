"""Silent Rust toolchain bootstrap with optional hash-pinned installer.

The rustup bootstrap script (sh.rustup.rs) is fetched once and verified
against a committed SHA256 manifest at ``scripts/rustup-init.sha256``
before being piped to ``sh``. This converts the standard ``curl | sh``
trust-by-TLS model into trust-by-committed-hash.

Maintenance flow
----------------
The Cortex maintainer refreshes the hash manifest after a verified
read of the upstream script:
    curl -sSf https://sh.rustup.rs | shasum -a 256 \\
      | awk '{print $1}' > scripts/rustup-init.sha256

If the manifest file is missing or empty, hash pinning is OFF and the
installer falls back to plain ``curl | sh`` with a warning emitted to
the audit dict (``hash_pin_status: "manifest_missing"``).

Override
--------
- ``CORTEX_RUSTUP_PIN_HASH=0`` — skip hash verification entirely.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from mcp_server.infrastructure.pipeline_installer_common import _run_quiet

# Disable Rust toolchain auto-install: CORTEX_AUTO_INSTALL_RUST=0.
_DISABLE_RUST_ENV = "CORTEX_AUTO_INSTALL_RUST"
_DISABLE_HASH_PIN_ENV = "CORTEX_RUSTUP_PIN_HASH"

# Canonical rustup installer URL — official Rust project mirror.
_RUSTUP_URL = "https://sh.rustup.rs"

# Where rustup puts cargo regardless of CARGO_HOME default.
_CARGO_HOME_BIN = Path.home() / ".cargo" / "bin"

# Hash manifest path — Cortex repo root + scripts/rustup-init.sha256.
# The repo root is two levels up from this module file
# (mcp_server/infrastructure/<this>.py).
_HASH_MANIFEST = Path(__file__).resolve().parents[2] / "scripts" / "rustup-init.sha256"


def resolve_cargo() -> Optional[str]:
    """Return cargo path: PATH first, then ``~/.cargo/bin/cargo``."""
    found = shutil.which("cargo")
    if found:
        return found
    candidate = _CARGO_HOME_BIN / "cargo"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _read_pinned_hash() -> Optional[str]:
    """Return the trimmed hex SHA256 from the manifest, or None."""
    try:
        raw = _HASH_MANIFEST.read_text().strip()
    except OSError:
        return None
    # Manifest format: hex digest on a line by itself, optional comment
    # lines starting with #. Take the first non-comment token.
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            token = line.split()[0]
            if len(token) == 64 and all(c in "0123456789abcdef" for c in token.lower()):
                return token.lower()
    return None


def install_rust_toolchain() -> dict:
    """Best-effort silent install of the Rust toolchain via rustup.

    Hash-verified path:
      1. Download the bootstrap script to a tempfile via ``curl``.
      2. Compute its SHA256.
      3. Compare against the pinned manifest (if present and non-empty).
      4. On match, ``sh tempfile -y --profile minimal --no-modify-path``.
      5. Mismatch → ``rust_hash_mismatch`` (does NOT execute the script).

    If the manifest is missing OR ``CORTEX_RUSTUP_PIN_HASH=0``, the
    installer falls back to the legacy curl-pipe-sh path with a status
    note in the result dict.

    Returns
    -------
    {
      action: "rust_already_present" | "rust_installed" | "rust_disabled"
              | "rust_curl_missing" | "rust_install_failed"
              | "rust_hash_mismatch",
      cargo:  <cargo path when present>,
      detail: <error tail when failed>,
      hash_pin_status: "verified" | "manifest_missing" | "disabled" | "skipped",
    }
    """
    if os.environ.get(_DISABLE_RUST_ENV, "").strip() in {"0", "false", "no"}:
        return {"action": "rust_disabled"}

    cargo = resolve_cargo()
    if cargo:
        return {"action": "rust_already_present", "cargo": cargo}

    curl = shutil.which("curl")
    if not curl:
        return {"action": "rust_curl_missing"}

    pin_disabled = os.environ.get(_DISABLE_HASH_PIN_ENV, "").strip() in {
        "0",
        "false",
        "no",
    }
    pinned_hash = None if pin_disabled else _read_pinned_hash()

    if pinned_hash:
        return _install_with_hash_pin(curl, pinned_hash)

    # Pin disabled or manifest missing — legacy curl-pipe-sh.
    pin_status = "disabled" if pin_disabled else "manifest_missing"
    cmd = (
        f"{shlex.quote(curl)} --proto '=https' --tlsv1.2 -sSf "
        f"{shlex.quote(_RUSTUP_URL)} | sh -s -- "
        f"-y --default-toolchain stable --profile minimal --no-modify-path"
    )
    rc, tail = _run_quiet(["sh", "-c", cmd], timeout=900)
    return _finalize_rust_install(rc, tail, pin_status)


def _install_with_hash_pin(curl: str, pinned_hash: str) -> dict:
    """Download → hash-verify → exec the rustup bootstrap script."""
    with tempfile.NamedTemporaryFile(
        prefix="rustup-init-", suffix=".sh", delete=False
    ) as tmp:
        tmp_path = tmp.name
    try:
        rc, tail = _run_quiet(
            [
                curl,
                "--proto",
                "=https",
                "--tlsv1.2",
                "-sSf",
                "-o",
                tmp_path,
                _RUSTUP_URL,
            ],
            timeout=120,
        )
        if rc != 0:
            return {
                "action": "rust_install_failed",
                "detail": f"download: {tail}",
                "hash_pin_status": "verified",
            }
        actual = _sha256_file(tmp_path)
        if actual != pinned_hash:
            return {
                "action": "rust_hash_mismatch",
                "detail": f"expected={pinned_hash} actual={actual}",
                "hash_pin_status": "verified",
            }
        rc, tail = _run_quiet(
            [
                "sh",
                tmp_path,
                "-y",
                "--default-toolchain",
                "stable",
                "--profile",
                "minimal",
                "--no-modify-path",
            ],
            timeout=900,
        )
        return _finalize_rust_install(rc, tail, "verified")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _finalize_rust_install(rc: int, tail: str, pin_status: str) -> dict:
    """Convert subprocess result into the audit dict."""
    if rc != 0:
        return {
            "action": "rust_install_failed",
            "detail": tail,
            "hash_pin_status": pin_status,
        }
    cargo = resolve_cargo()
    if not cargo:
        return {
            "action": "rust_install_failed",
            "detail": "cargo not found after rustup",
            "hash_pin_status": pin_status,
        }
    return {
        "action": "rust_installed",
        "cargo": cargo,
        "hash_pin_status": pin_status,
    }


def _sha256_file(path: str) -> str:
    """Stream-hash a file with SHA256. Constant-memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
