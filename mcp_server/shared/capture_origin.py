"""Shared capture provenance vocabulary and read-trust policy.

source: ADR-0114
"""

ORIGIN_DELIBERATE = "deliberate"
ORIGIN_LOCAL_ACTION = "local_action"
ORIGIN_NETWORK = "network"
ORIGIN_UNKNOWN = "unknown"
ORIGIN_LEGACY = "legacy"

ALL_ORIGINS: tuple[str, ...] = (
    ORIGIN_DELIBERATE,
    ORIGIN_LOCAL_ACTION,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
    ORIGIN_LEGACY,
)

TRUSTED_ORIGINS_AT_READ: frozenset[str] = frozenset(
    {ORIGIN_DELIBERATE, ORIGIN_LOCAL_ACTION, ORIGIN_LEGACY}
)
