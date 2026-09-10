"""Prebuilt binary fast-path for the upstream pipeline install.

When upstream publishes a GitHub Release with a per-platform tarball,
fetching + extracting it is ~10 s vs ~6 min for git+cargo. This module
implements the fast path with strict integrity gates:

source: ADR-0587"""

from __future__ import annotations

import hashlib
import json
import os
import platform

from mcp_server.infrastructure.upstream_identity import (
    BINARY_NAMES,
    CANONICAL_BINARY,
    RELEASES_LATEST_URL,
)
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_RELEASES_URL = RELEASES_LATEST_URL
_REQUEST_TIMEOUT = 30  # seconds
_DISABLE_ENV = "CORTEX_DISABLE_PREBUILT"
# source: ADR-0587
_SHA256_HEX_LEN = 64


def _platform_tag() -> Optional[str]:
    """Return ``{os}-{arch}`` for the running host, or None if unsupported."""
    sys = platform.system().lower()
    mach = platform.machine().lower()
    os_tag = {"darwin": "macos", "linux": "linux"}.get(sys)
    arch_tag = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }.get(mach)
    if not os_tag or not arch_tag:
        return None
    return f"{os_tag}-{arch_tag}"


def _http_get(url: str, accept: Optional[str] = None) -> bytes:
    """Plain-Python HTTPS GET. Raises on any error.

    source: ADR-0587"""
    req = urllib.request.Request(url)
    if accept:
        req.add_header("Accept", accept)
    req.add_header("User-Agent", "cortex-installer")
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        return resp.read()


def _find_assets(release: dict, tag: str) -> Optional[tuple[str, str]]:
    """Return ``(tarball_url, sha256_url)`` for the host platform tag.

    Matches by suffix, not exact name, so upstream can prefix versions.
    """
    tar_url = sha_url = None
    suffix = f"-{tag}.tar.gz"
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        url = asset.get("browser_download_url")
        if not url:
            continue
        if name.endswith(suffix):
            tar_url = url
        elif name.endswith(suffix + ".sha256"):
            sha_url = url
    if tar_url and sha_url:
        return tar_url, sha_url
    return None


def _verify_and_extract(
    tar_path: str, expected_sha: str, dest_dir: str
) -> Optional[str]:
    """Verify SHA256, extract the upstream binary to dest_dir, return path.

    source: ADR-0587"""
    h = hashlib.sha256()
    with open(tar_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    if h.hexdigest() != expected_sha.lower():
        return None
    dest = Path(dest_dir).resolve()
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            # source: ADR-0587
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest) + os.sep) and target != dest:
                return None
            if member.isfile() and Path(member.name).name in BINARY_NAMES:
                # source: ADR-0587
                tar.extract(member, dest_dir, filter="data")
                extracted = dest / member.name
                os.chmod(extracted, 0o755)
                return str(extracted)
    return None


def try_install_prebuilt(symlink_dest: Path) -> dict:
    """Try the fast path. Returns audit dict.

    source: ADR-0587"""
    if os.environ.get(_DISABLE_ENV, "").strip() in {"1", "true", "yes"}:
        return {"action": "prebuilt_disabled"}

    tag = _platform_tag()
    if not tag:
        return {"action": "prebuilt_unsupported_platform"}

    try:
        body = _http_get(_RELEASES_URL, accept="application/vnd.github+json")
        release = json.loads(body)
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return {"action": "prebuilt_unavailable", "detail": f"releases api: {exc}"}

    found = _find_assets(release, tag)
    if not found:
        return {"action": "prebuilt_unavailable", "detail": f"no asset for {tag}"}
    tar_url, sha_url = found

    work = Path(tempfile.mkdtemp(prefix="cortex-prebuilt-"))
    try:
        try:
            tar_bytes = _http_get(tar_url)
            sha_bytes = _http_get(sha_url)
        except (urllib.error.URLError, OSError) as exc:
            return {"action": "prebuilt_unavailable", "detail": f"download: {exc}"}

        tar_path = work / "asset.tar.gz"
        tar_path.write_bytes(tar_bytes)
        # Manifest format: ``<sha256>  <filename>`` (shasum -a 256 style)
        # — first whitespace-separated token is the digest.
        digest_text = sha_bytes.decode("utf-8", errors="replace").strip()
        expected_sha = digest_text.split()[0] if digest_text else ""
        if len(expected_sha) != _SHA256_HEX_LEN:
            return {
                "action": "prebuilt_unavailable",
                "detail": "malformed sha256 manifest",
            }

        binary = _verify_and_extract(str(tar_path), expected_sha, str(work))
        if not binary:
            return {
                "action": "prebuilt_unavailable",
                "detail": "hash mismatch or no binary in archive",
            }

        # source: ADR-0587
        symlink_dest.parent.mkdir(parents=True, exist_ok=True)
        final = symlink_dest.parent / f"{CANONICAL_BINARY}.prebuilt"
        shutil.move(binary, str(final))
        os.chmod(final, 0o755)

        # source: ADR-0587
        tmp_link = symlink_dest.with_name(symlink_dest.name + ".new")
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        tmp_link.symlink_to(final)
        os.replace(str(tmp_link), str(symlink_dest))

        return {
            "action": "installed_prebuilt",
            "binary": str(symlink_dest),
            "tag": release.get("tag_name"),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
