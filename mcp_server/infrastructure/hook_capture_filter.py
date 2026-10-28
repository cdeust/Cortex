"""Automatic injection permits trusted, non-capture provenance only.

Only internal SQL fragments are exposed; user values remain bound parameters.
Default tool recall has a separate visibility policy: unknown memories remain
available to explicit recall, but cannot silently become automatic context.
"""

from mcp_server.shared.capture_origin import (
    ORIGIN_DELIBERATE,
    ORIGIN_LOCAL_ACTION,
    TRUSTED_ORIGINS_AT_READ,
)

# source: ADR-0114 read-trust allowlist and issue #706 capture exclusion.
# These values are repository-owned origin enums, never caller-provided SQL.
_HOOK_ORIGINS = tuple(
    origin for origin in sorted(TRUSTED_ORIGINS_AT_READ)
    if origin != ORIGIN_LOCAL_ACTION
)
_ORIGIN_SQL = ", ".join(repr(origin) for origin in _HOOK_ORIGINS)
HOOK_CAPTURE_FILTER = (
    f"(m.capture_origin = '{ORIGIN_DELIBERATE}' OR "
    f"(m.capture_origin IN ({_ORIGIN_SQL}) "
    "AND COALESCE(m.source, '') <> 'post_tool_capture'))"
)
