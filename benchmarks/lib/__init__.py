"""Shared benchmark library — retrieval, fusion, and PG database helpers.

``BenchmarkDB`` is re-exported lazily (PEP 562 module ``__getattr__``)
rather than imported eagerly at the top: ``bench_db.py`` hard-imports
``psycopg``/``psycopg_pool``/``pgvector`` at module scope (issue #282),
and every other consumer in this package already defers that same import
inside a function for exactly this reason (see the "deferred: module
hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would
break installs without it" comments in ``ablation_runner.py``,
``bench_db.py``, ``_xb_drivers.py``, ``longitudinal_runner.py``,
``llm_head_to_head/pilot.py``). Eagerly importing it here at package-init
time — as this module did before — made every other submodule
(``benchmarks.lib.verification_report`` included) unimportable on an
install without the Postgres extras, since Python always runs a
package's ``__init__.py`` before any of its submodules.
"""

from benchmarks.lib.fusion import (
    wrrf_fuse,
    QualityZone,
    assess_quality_zone,
    enforce_chunk_limit,
)
from benchmarks.lib.retriever import BenchmarkRetriever

__all__ = [
    "BenchmarkDB",
    "BenchmarkRetriever",
    "wrrf_fuse",
    "QualityZone",
    "assess_quality_zone",
    "enforce_chunk_limit",
]


def __getattr__(name: str):
    """Lazily resolve ``BenchmarkDB`` on first access (PEP 562).

    Precondition: ``name`` is an attribute looked up on this module that
    was not found among its eagerly-bound names above.
    Postcondition: returns ``bench_db.BenchmarkDB`` for
    ``name == "BenchmarkDB"`` — raising whatever ``ImportError`` psycopg's
    own absence produces, deferred until actually needed — else raises
    ``AttributeError`` (the standard module-attribute-not-found contract).
    """
    if name == "BenchmarkDB":
        from benchmarks.lib.bench_db import (  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it
            BenchmarkDB,
        )

        return BenchmarkDB
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")  # noqa: TRY003 — mirrors Python's own standard module-attribute-not-found message (PEP 562); not reused (§3.3)
