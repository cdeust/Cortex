"""Bidirectional conversion between filesystem paths, Claude project IDs,
human-readable labels, and domain identifiers.

source: ADR-0662"""

from __future__ import annotations

import re

_STRIP_PREFIX_RE = re.compile(r"^-?Users-[^-]+(-Documents)?(-Developments)?-")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_LEADING_TRAILING_DASH_RE = re.compile(r"^-|-$")

# Drive-letter prefix: "C:", "C:/", "C:\\". The colon is the structural marker.
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# source: ADR-0662


_GITBASH_DRIVE_RE = re.compile(r"^/([A-Za-z])/")
# Whole-string non-alphanumeric (incl. ':', '\\', '/', '.') for Windows slug.
_WINDOWS_SLUG_RE = re.compile(r"[^a-z0-9]")


def _is_windows_path(path: str) -> bool:
    """True if path looks like a Windows absolute path (drive letter)."""
    return bool(_WINDOWS_DRIVE_RE.match(path))


def _gitbash_to_windows(path: str) -> str | None:
    """Convert '/c/users/foo' → 'c:/users/foo'. Returns None if not gitbash."""
    m = _GITBASH_DRIVE_RE.match(path)
    if not m:
        return None
    drive = m.group(1)
    return f"{drive}:/{path[3:]}"


def _windows_slug(path: str) -> str:
    """Normalize a Windows-style absolute path to its on-disk Claude slug.

    source: ADR-0662"""
    return _WINDOWS_SLUG_RE.sub("-", path.lower())


def cwd_to_project_id(cwd: str | None) -> str | None:
    """Convert a working directory path to a Claude project ID.

    source: ADR-0662"""
    if not cwd:
        return None

    # Git-Bash drive translation '/c/...' canonicalizes to Windows form first.
    gb = _gitbash_to_windows(cwd)
    if gb is not None:
        return _windows_slug(gb)

    # Windows absolute path: full lowercase + per-char non-alnum→'-'.
    if _is_windows_path(cwd):
        return _windows_slug(cwd)

    # source: ADR-0662

    return cwd.replace("\\", "/").replace("/", "-")


def normalize_project_id(project_id: str | None) -> str | None:
    """Case-fold a project ID for equality/membership comparisons.

    Preconditions:
        - project_id is None, empty, or a string either produced by
          cwd_to_project_id or read verbatim from profiles.json's
          ``projects`` list (which is populated at profile-write time from
          on-disk Claude project directory names, not from this module).
    Postconditions:
        - Returns None when project_id is None or empty.
        - Otherwise returns the lowercased string.

    source: ADR-0662

    Two project directories differing only by case (e.g. `Foo` and `foo`)
    could in principle collide under this fold on a case-sensitive
    filesystem (Linux, most macOS). This is accepted: (a) it requires two
    sibling directories named identically but for case, which is
    vanishingly rare in practice; (b) the failure mode is a session
    misattributed to the sibling domain, recoverable via
    ``rebuild_profiles``, not data loss; (c) it is far smaller in impact
    than the status quo, where every Windows user with any uppercase
    character anywhere in their project path gets zero profile-based
    domain detection.
    """
    if not project_id:
        return None
    return project_id.lower()


def project_id_to_label(project_id: str | None) -> str:
    """Convert a Claude project ID to a human-readable label.

    source: ADR-0662"""
    if not project_id:
        return "Unknown"
    result = _STRIP_PREFIX_RE.sub("", project_id).replace("-", " ").strip()
    return result or project_id


def domain_id_from_label(label: str | None) -> str:
    """Convert a human-readable label to a kebab-case domain ID."""
    if not label:
        return ""
    result = _NON_ALNUM_RE.sub("-", label.lower())
    return _LEADING_TRAILING_DASH_RE.sub("", result)
