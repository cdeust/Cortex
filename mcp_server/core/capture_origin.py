"""Capture origin — which CHANNEL produced a memory's content.

source: ADR-0114
"""

from __future__ import annotations

# source: ADR-0114


from mcp_server.shared.capture_origin import (
    ALL_ORIGINS as ALL_ORIGINS,
    ORIGIN_DELIBERATE,
    ORIGIN_LEGACY as ORIGIN_LEGACY,
    ORIGIN_LOCAL_ACTION,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
    TRUSTED_ORIGINS_AT_READ,
)

# source: ADR-0114


_NETWORK_TOOLS: frozenset[str] = frozenset({"webfetch", "websearch"})

# source: ADR-0114


_LOCAL_ACTION_TOOLS: frozenset[str] = frozenset(
    {
        "edit",
        "write",
        "multiedit",
        "notebookedit",
        "notebookread",
        "bash",
        "read",
        "glob",
        "grep",
    }
)

# source: ADR-0114


_ORIGINS_ALLOWED_CONTENT_BYPASS: frozenset[str] = frozenset(
    {ORIGIN_DELIBERATE, ORIGIN_LOCAL_ACTION}
)



def classify_capture_origin(tool_name: str) -> str:
    """Map a producing tool name to its capture origin.

    source: ADR-0114

    Never inspects content: the argument is a tool name by construction.
    """
    # source: ADR-0114

    key = (tool_name or "").strip().lower()
    if key in _NETWORK_TOOLS:
        return ORIGIN_NETWORK
    if key in _LOCAL_ACTION_TOOLS:
        return ORIGIN_LOCAL_ACTION
    return ORIGIN_UNKNOWN


def may_bypass_write_gate_on_content(origin: str) -> bool:
    """Whether content from ``origin`` may claim a content-derived bypass.

    Pre: ``origin`` is any string.
    Post: True exactly for the origins in
    ``_ORIGINS_ALLOWED_CONTENT_BYPASS``; False otherwise, including for
    ``ORIGIN_UNKNOWN`` and for any value this module does not recognise.

    source: ADR-0114"""
    return origin in _ORIGINS_ALLOWED_CONTENT_BYPASS


def is_network_origin(origin: str) -> bool:
    """True when ``origin`` denotes content fetched from off this machine."""
    return origin == ORIGIN_NETWORK


def is_trusted_at_read(origin: str) -> bool:
    """Whether ``origin`` keeps full ranking weight and may earn heat.

    Pre: ``origin`` is any string.
    Post: True exactly for ``TRUSTED_ORIGINS_AT_READ``; False otherwise,
    including for ``ORIGIN_UNKNOWN`` and unrecognised values.

    source: ADR-0114"""
    return origin in TRUSTED_ORIGINS_AT_READ


def trust_factor(origin: str, untrusted_factor: float) -> float:
    """Ranking multiplier for content captured through ``origin``.

    source: ADR-0114"""
    return 1.0 if origin in TRUSTED_ORIGINS_AT_READ else untrusted_factor


def trusted_origins_at_read() -> tuple[str, ...]:
    """The origins that keep full ranking weight, for backends that filter
    server-side.

    source: ADR-0114"""
    return tuple(sorted(TRUSTED_ORIGINS_AT_READ))
