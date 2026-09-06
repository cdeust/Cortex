"""Keep explicit Claude roots independent from legacy global hook state."""

from __future__ import annotations

import os
from pathlib import Path


def cooldown_path(filename: str) -> Path:
    """Honor config.py's override; preserve the existing default /tmp path."""
    override = os.environ.get("CORTEX_CLAUDE_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "methodology" / "hook-cooldowns" / filename
    return Path("/tmp") / filename
