# Model identity: what a local run can name today (2026-11-06)

Issue #734, slice 1: before building one effective model manifest, list which
facts about the embedding model and the reranker Cortex records today, where
each one is exposed, and where a recorded value does not describe what the run
actually served. This document changes no behaviour. Every row cites the code
read at `main` `79bd6c3`; the runtime probe is reproduced below.

## The two models

| Fact | Embedding (`EmbeddingEngine`) | Reranker (FlashRank) |
| --- | --- | --- |
| Name | `all-MiniLM-L6-v2`, constructor default (`infrastructure/embedding_engine.py`) | `ms-marco-MiniLM-L-12-v2`, file `flashrank-MiniLM-L-12-v2_Q.onnx` (`core/reranker_model.py`) |
| Pinned identity | Hugging Face revision `DEFAULT_MODEL_REVISION` = `1110a243…4d41`, passed to `SentenceTransformer(revision=...)` (`infrastructure/embedding_model_lifecycle.py`) | none: `Ranker(model_name=..., cache_dir=...)` takes a name only (`core/reranker.py::_ensure_reranker`) |
| Digest of the bytes | none: no file of the embedding cache is hashed anywhere in `mcp_server/` | `model_sha256()`: sha256 of the on-disk ONNX file, or `None` when absent (`infrastructure/reranker_cache.py`) |
| Expected digest | not applicable | none in code. The value `d3dd7b09…41d1` appears only in committed results (131 occurrences under `benchmarks/results/`), never compared against |
| Load state | `ModelState`: `UNINITIALIZED`, `LOADED`, `PACKAGE_ABSENT`, `MODEL_FILES_ABSENT`, `LOAD_RAISED` | `RerankerStatus.state`: `loaded`, `failed` (with `error`), `not_attempted` |
| Device | `_device`, resolved once from `EMBEDDING_DEVICE` (`cpu` default, or `auto`/`cuda`/`mps`); a GPU inference error reloads on CPU (`_fallback_to_cpu`) | not chosen by Cortex: FlashRank 0.2.10 opens an `onnxruntime.InferenceSession` with its default providers |
| Fallback | any non-`LOADED` state serves the download-free algorithmic embedding (`embedding_factory.py::use_fallback`) | a failed load disables reranking for the process; recall keeps first-stage WRRF scores |
| Offline guard | `local_files_only=True` first; a cache miss starts a background download (`embedding_downloads.py`) | `CORTEX_RERANKER_OFFLINE` refuses the fetch when the file is absent; the check is existence only, not identity |

## Where each fact is exposed

| Surface | Embedding | Reranker | Source |
| --- | --- | --- | --- |
| `get_telemetry` | `embedding_mode`: `neural`, `fallback` or `unknown`, per process | nothing | `handlers/get_telemetry.py` |
| `cortex doctor` | `sentence_transformers` importable or not (`doctor_mcp.py::_check_optional_imports`) | nothing reported; `ensure_reranker_ready` preloads for CI only | `doctor.py`, `doctor_mcp.py` |
| Stored memory (SQLite only) | `memories.embedding_model` holds the *mode* (`neural`/`fallback`), not the model name or revision | not applicable | `infrastructure/sqlite_store.py::_stamp_embedding_model` |
| Benchmark manifest (`benchmarks/lib/write_manifest.py`) | `embedding_model_revision`, package versions | `reranker_active`, `reranker_state`, `reranker_model_sha256` | `_environment_fields` |
| Repro manifest (`benchmarks/_repro.py`, LongMemEval, LoCoMo, BEAM) | package versions only | `reranker_state`, `reranker_model_path`, `reranker_model_sha256` | `build_repro_manifest` |

No surface reports the embedding device, the embedding `ModelState`, the
reranker's device or inference provider, or an engine and plugin identity next
to the model facts (`doctor_artifact.py`, #729, names the artifact but no
model).

## Where a recorded value does not describe the run

- **The embedding revision is the configured pin, not what was loaded.**
  `EmbeddingEngine.revision` returns the constructor argument whatever the
  load state. `write_manifest.embedding_revision()` records it under
  `embedding_model_revision`, and its docstring says "Exact model revision this
  run's EmbeddingEngine loaded". In the probe below the engine is in
  `PACKAGE_ABSENT` and serves fallback vectors, and the manifest still records
  `1110a243…4d41`. Neither manifest records the embedding mode, so a fallback
  run and a neural run produce the same embedding fields.
- **The repro manifest has no embedding identity at all**: the three headline
  benchmarks record `sentence-transformers` and `torch` versions, not the model
  name, revision or mode.
- **The reranker digest is recorded, never verified.** A changed or corrupt
  ONNX file that FlashRank still loads gives `reranker_state: loaded` and a
  different sha256 in the manifest; nothing compares it with the value the
  committed results carry, and `cortex doctor` does not look.
- **A stored vector names its space, not its model.** The `neural`/`fallback`
  stamp keeps fallback and neural vectors apart (ADR-0616), but two neural
  models of the same dimension would be stamped alike.

Probe (this container, `main` `79bd6c3`, Python 3.11, locked dependencies
without `torch` and `sentence-transformers`, `CORTEX_RERANKER_OFFLINE=1`, no
model downloaded):

```python
from mcp_server.infrastructure.embedding_factory import get_embedding_engine
from benchmarks.lib.write_manifest import embedding_revision, reranker_fields

e = get_embedding_engine()
e.mode, e.model_state, e.revision
# ('fallback', <ModelState.PACKAGE_ABSENT: 3>, '1110a243fdf4706b3f48f1d95db1a4f5529b4d41')
embedding_revision()  # '1110a243fdf4706b3f48f1d95db1a4f5529b4d41'
reranker_fields()  # {'reranker_active': False, 'reranker_state': 'failed',
#  'reranker_model_sha256': None}
```

## Remaining slices of #734

1. Record what was served: the embedding mode and `ModelState` beside
   `embedding_model_revision` in both manifests, and the revision only when the
   state is `LOADED`.
2. One effective manifest (engine and plugin identity from `doctor_artifact`,
   backend, model names, revision and digests, devices, mode) built in one
   place and returned by `cortex doctor` and the benchmark manifests, without
   content or sensitive configuration.
3. Verify provisioned models against a pinned identity (an expected reranker
   sha256, a digest of the embedding snapshot files) and report missing,
   corrupt or incompatible states.
4. A receipt of memory operations with networking disabled after provisioning,
   each result labelled with the mode it ran in.

Not verified here: a `LOADED` neural engine and a loaded FlashRank model
(neither could be downloaded through this container's proxy), GPU devices, and
the PostgreSQL store. The PostgreSQL code has no `embedding_model` column at
all (no match outside the SQLite files of `mcp_server/infrastructure/`), so the
stamp row above holds for SQLite only. Rows for those paths are read from the
code.
