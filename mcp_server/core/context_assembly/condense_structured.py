"""Condenser for structured (subject, predicate, object) content (issue #228
split 3/4).

Extracted from ``condensers.py`` (§4.1 — the original file was 391 lines,
over this repo's 300-line cap) with zero behaviour change. See
``condensers.py`` for the shared module docstring and re-export facade.
"""

from __future__ import annotations

import re

from mcp_server.core.context_assembly.budget import (
    estimate_tokens,
    truncate_to_budget,
)

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_ARROWS_FOR_TRIPLES = 2


# ── Entity-triple condenser ─────────────────────────────────────────────
# Strategy: keep (subject, predicate, object) triples verbatim, drop
# anything else. Triples are already maximally compressed.


def condense_entity_triples(text: str, token_budget: int) -> str:
    """Keep only lines matching triple patterns, in budget order."""
    if estimate_tokens(text) <= token_budget:
        return text
    triple_re = re.compile(
        r"^\s*([^→\->:]+?)\s*(?:→|->|:)\s*([^→\->:]+?)\s*(?:→|->|:)\s*(.+?)\s*$"
    )
    kept_lines: list[str] = []
    used = 0
    for line in text.split("\n"):
        if triple_re.match(line):
            t = estimate_tokens(line)
            if used + t > token_budget:
                break
            kept_lines.append(line)
            used += t
    if kept_lines:
        return "\n".join(kept_lines)
    return truncate_to_budget(text, token_budget)
