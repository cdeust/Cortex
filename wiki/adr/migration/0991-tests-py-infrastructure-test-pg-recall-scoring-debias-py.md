# ADR-0991: tests_py/infrastructure/test_pg_recall_scoring_debias.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/infrastructure/test_pg_recall_scoring_debias.py`, original SHA-256 `b567b4264af8376863bbf6bde7730163e551a90ec9ecb536182c7175ceccb50c`.
Assertions and runtime fixture literals remain unchanged.

## Original comment, lines 117–126

````text
# A 30-day-old curated lesson is realistically CONSOLIDATED, not
# labile: the consolidation cascade advances it long before 30 days.
# The stage matters now that insert_memory anchors the decay clock to
# created_at — a labile (α=2.0) memory backdated 30 days correctly
# decays below min_heat and would be filtered. The 'consolidated'
# stage (α=0.5, permastore floor 0.10) models the real lifecycle and
# keeps the lesson retrievable, so this test still exercises the
# content-debias path rather than an artificial decay-to-floor.
# Source: A3 decay-clock anchor (pg_store.insert_memory);
# effective_heat() stage table pg_schema.py:652-678.
````

