# Replacement of stale PR proposals

Owner instruction, 2026-10-27: "Then clear these PR and build new one with what main shows".
Base verified through GitHub and Git: `8b00ded376ed3404ef9fda6c2afbcbdeb95c3e93`.

| Closed proposal | Preserved head | Current-main assessment |
| --- | --- | --- |
| [PR776](https://github.com/cdeust/Cortex/pull/776) | `2ab0a57d801f788ee6e601a4d0df569a43393185` | Decay still yields inside a reader transaction; failed DDL can record a completed revision; query recovery can replay a write after a lost response. Existing store caching, managed PostgreSQL, security gates and erasure narrow the broker proposal. |
| [PR773](https://github.com/cdeust/Cortex/pull/773) | `45ab0a467b2f54e5c4a5f4832e01ff6b45ebd08b` | Current sensory-buffer delivery tests call symbols the old inventory deletes. No deletions are carried forward. |
| [PR738](https://github.com/cdeust/Cortex/pull/738) | `360aa92d239d609168d8a9cbb6588edd96a8220a` | Main still needs the absolute Bash resolver, but has removed the proposed integration target, `ci.yml`. |

The original branches remain on GitHub. The full broker draft and its immutable source-blob map are preserved separately in the maintainer's `tasks/pr776-remote-merge-checkpoint.json`; that draft was not applied or executed here.

The replacement uses bounded ID pages and releases the batch connection before yielding. A maximum ID captured at the start keeps the pass finite during inserts. Deletions between pages do not shift an offset and skip surviving rows. Each page observes its own current database state; this is not a cross-page snapshot.

Schema upgrades retain main's constructor contract, which existing upgrade tests explicitly require. DDL and the revision record now commit together under a transaction-scoped advisory lock. Failure rolls both back and closes a failed constructor's connection. Broad `OperationalError` replay is removed because a lost response does not establish that a write failed to execute.

The Bash changes retain the surviving callers from PR738. The current Pipeline environment command runs the resolved binary on each supported host. ADR1101 was regenerated through Cortex `wiki_write`; the manifest keeps main's existing entries.

## Local verification

Tests used a fresh uv.lock-resolved Python 3.13.7 environment and a private PostgreSQL 17 cluster with a Unix socket under a registered disposable directory. There was no TCP listener or live-store access. `CORTEX_TEST_DATABASE_URL` explicitly selected that private database; `CORTEX_MEMORY_STORE_BACKEND=postgresql` and `PYTHONDONTWRITEBYTECODE=1` were set.

- On unchanged main, the three initial transaction regression tests failed: write execution count was 2; one backend was idle in a transaction between decay chunks; failed DDL did not raise. The resolver contract failed collection because the public resolver was absent.
- After implementation, `pytest -q -p no:randomly --tb=short tests_py/infrastructure/test_pg*.py tests_py/infrastructure/test_s110_sweep_infrastructure.py tests_py/test_migrate.py`: 271 passed.
- Final affected shell, platform, environment-helper and transaction tests: 98 passed and 9 subtests passed.
- Empty-database `python -m mcp_server.migrate`: exit 0, applied 99 statements.
- Ruff 0.17.1 checks and formatting pass on the changed Python files. Pyright 1.1.414 checks the four changed runtime modules.
- Repository craftsmanship check uses `--base origin/main`. The staged source checker reports no findings. The shared craftsmanship scanner reports advisory layer warnings because it reads the `server` token in `mcp_server.infrastructure` as an outer layer; the repository's AST layer check passes. Its indentation heuristic also flags the conditional SQL expression. No gate configuration or baseline was changed.

Hosted CI, native Windows execution and native Codex review remain external acceptance signals. These local results make no claim about broker capacity or latency. Host-wide pooling and removal of runtime schema upgrades require separate evidence and are outside this replacement.
