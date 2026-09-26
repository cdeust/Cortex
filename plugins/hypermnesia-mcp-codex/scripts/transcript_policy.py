"""Transcript deletion requires explicit owner configuration. source: ADR-1092"""

import os


def delete_enabled() -> bool:
    """Reject typos before any cleanup rather than silently changing retention."""
    value = os.environ.get("CORTEX_CLEANUP_TRANSCRIPTS", "keep")
    if value not in ("keep", "delete"):
        raise ValueError("CORTEX_CLEANUP_TRANSCRIPTS must be keep or delete")
    return value == "delete"
