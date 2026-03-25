"""Bidirectional conversion between filesystem paths, Claude project IDs,
human-readable labels, and domain identifiers.

Claude Code stores project data in directories named by mangled filesystem paths
(e.g., "-Users-dev-myproject").
"""

from __future__ import annotations

import re

_STRIP_PREFIX_RE = re.compile(r"^-?Users-[^-]+(-Documents)?(-Developments)?-")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_LEADING_TRAILING_DASH_RE = re.compile(r"^-|-$")


def cwd_to_project_id(cwd: str | None) -> str | None:
    """Convert a working directory path to a Claude project ID.

    /Users/dev/cortex -> -Users-dev-cortex
    """
    if not cwd:
        return None
    return cwd.replace("/", "-")


def project_id_to_label(project_id: str | None) -> str:
    """Convert a Claude project ID to a human-readable label.

    Strips common path prefixes (Users, Documents, Developments)
    and replaces dashes with spaces.
    """
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
