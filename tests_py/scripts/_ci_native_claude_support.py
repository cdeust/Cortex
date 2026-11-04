"""Shared accessors for the owner @claude mention workflow tests (claude.yml)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MENTIONS = ROOT / ".github/workflows/claude.yml"
ACTION = "anthropics/claude-code-action@8041f1d17e0e7d2f2cfe35002962e9f26237c0bb"
GUARD = "Authorize owner fix target"


def mention_job():
    return yaml.safe_load(MENTIONS.read_text())["jobs"]["claude"]


def find_step(job, *, name=None, uses=None):
    return next(
        s
        for s in job["steps"]
        if (name is not None and s.get("name") == name)
        or (uses is not None and s.get("uses", "").startswith(uses))
    )
