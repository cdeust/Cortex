"""BEAM-10M LLM Head-to-Head Harness.

Stage-0 scaffold for the pre-registered protocol at
``tasks/beam-10m-llm-head-to-head-protocol.md`` (v3, frozen 2026-04-30).

Four conditions feed the SAME generator prompt:
  A — naive long-context (recency-truncated to model window)
  B — standard top-20 vector RAG (Lewis 2020, no Cortex stack)
  C — Cortex-assembled (production ``handlers.recall.handler``)
  D — Oracle (gold ``source_chat_ids`` turns)

NO API spend at scaffold stage; the orchestrator's ``--dry-run`` mode
must produce all four context blocks without firing any HTTP requests.
"""

# precondition: package import is side-effect free; no API keys read here.
# postcondition: re-exporting module names resolves cleanly so callers can
#   ``from benchmarks.llm_head_to_head import data_loader`` without import-
#   time network or DB access.

__all__ = [
    "data_loader",
    "long_context_truncator",
    "retriever_baselines",
    "cortex_caller",
    "oracle_loader",
    "generator",
    "judge",
    "manifest",
    "orchestrator",
    "pilot",
]
