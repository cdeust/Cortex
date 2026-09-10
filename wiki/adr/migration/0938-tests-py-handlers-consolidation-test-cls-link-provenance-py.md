# ADR-0938: tests_py/handlers/consolidation/test_cls_link_provenance.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/handlers/consolidation/test_cls_link_provenance.py`, original SHA-256 `6c51de391bdcecf5751c7777b32134d0029de27828d0b2c59a3bd97385c4628b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–10

````text
"""Tests for CLS source-memory provenance (fix/memory-link-fk-violation).

Root cause: `_link_source_memories` (removed) passed episodic MEMORY ids into
`store.insert_relationship`, whose `source_entity_id`/`target_entity_id`
columns are `NOT NULL REFERENCES entities(id)` -- every call violated the FK
and was swallowed by a bare `except Exception: pass`, so no source->semantic
link was ever persisted. The fix embeds provenance in the new memory's own
`tags` at insert time instead (`derived-src:<memory_id>`), reusing the
convention `handlers/consolidation/memify_derive.py` already established.
"""
````

