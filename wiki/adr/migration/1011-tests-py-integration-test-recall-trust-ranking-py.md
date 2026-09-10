# ADR-1011: tests_py/integration/test_recall_trust_ranking.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/integration/test_recall_trust_ranking.py`, original SHA-256 `62603995c8547b60d5109dc5d7d73e65b0df13b05b2348ccb93c703c77688c44`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–16

````text
"""Trust/provenance ranking under adversarial retrieval poisoning (issue #368).

The property under test: a memory whose capture_origin is untrusted must not
outrank a trusted one that answers the same query, even when the untrusted
passage wins on pure similarity. Before the trust term exists these tests
fail — that failure IS the measurement of the attack, and it is why the
corpus declares its hostile entries with the higher similarity.

Skip pattern mirrors tests_py/integration/test_recall_e2e.py: import _USE_PG
from conftest and apply pytestmark, so the module skips cleanly when PG is
absent rather than erroring at collection.

Source: arXiv 2604.16548 (retrieve-phase corruption; "Retrieval-time
filtering alone is insufficient"). The assertions therefore read the ORDER
produced by the ranking function, never a post-hoc filtered list.
"""
````

