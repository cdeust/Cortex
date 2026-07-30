"""Domain-aware condensers per Cortex memory type.

Each condenser reduces a piece of content to fit a token budget, using
domain knowledge of **what matters** for that content type. Generic
truncation loses the most important information first (it keeps the
first N tokens regardless of significance); domain-aware condensers
preserve high-signal content and drop filler.

Adapted from Clément Deust's Swift condensers in ContextDecomposer.swift
(`condenseContracts`, `condenseEngineGraph`, `condenseFileTree`,
`condenseImpactReport`), plus Cortex-specific memory types.

Issue #228 split this module (was 391 lines, over this repo's 300-line
§4.1 cap, with two functions over the 40-line §4.2 cap) into one file per
condenser family, behaviour-preserving:

- ``condense_text.py`` — user-message and timeline-event condensers
  (sentence-slot strategies) + their sentence-splitting helpers.
- ``condense_code.py`` — code-block and assistant-message condensers
  (verbatim-code strategies) + their fence-splitting helpers.
- ``condense_structured.py`` — the entity-triple condenser.
- ``condense_dispatch.py`` — ``condense_memory_content``, the
  shape/tag-driven dispatcher over the three families above.
- ``condense_stage.py`` — ``condense_assembled_context``, the
  stage-assembler integration point (issue #196).

This module re-exports every public name (plus the private helpers the
issue #228 test suite targets directly) so every existing import path
(``from mcp_server.core.context_assembly.condensers import ...``,
including patch targets in tests) keeps resolving unchanged — the split
is an internal reorganization, not an API change.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.condense_code import (
    _has_code_blocks as _has_code_blocks,
)
from mcp_server.core.context_assembly.condense_code import (
    _split_by_code_blocks as _split_by_code_blocks,
)
from mcp_server.core.context_assembly.condense_code import (
    condense_assistant_message,
    condense_code_block,
)
from mcp_server.core.context_assembly.condense_dispatch import condense_memory_content
from mcp_server.core.context_assembly.condense_stage import condense_assembled_context
from mcp_server.core.context_assembly.condense_structured import (
    condense_entity_triples,
)
from mcp_server.core.context_assembly.condense_text import (
    _first_sentence as _first_sentence,
)
from mcp_server.core.context_assembly.condense_text import (
    _split_sentences as _split_sentences,
)
from mcp_server.core.context_assembly.condense_text import (
    condense_timeline_event,
    condense_user_message,
)

__all__ = [
    "condense_assembled_context",
    "condense_assistant_message",
    "condense_code_block",
    "condense_entity_triples",
    "condense_memory_content",
    "condense_timeline_event",
    "condense_user_message",
]
