"""The error raised when a Codex hook event cannot be translated safely."""

from __future__ import annotations


class HostEventError(ValueError):
    """The host event cannot be normalized without losing edit information."""
