# Memory Tool Contract — Local Replication of `memory_20250818`

**Status**: binding. No implementation may ship until this contract is satisfied.
**Source of truth**: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool>
**Scope**: defines the behavioral contract every memory backend (local FS, Cortex MCP, future alternatives) MUST satisfy for Liskov substitutability.

---

## 1. Tool identity

| Field | Value |
|---|---|
| Tool type | `memory_20250818` |
| Tool name | `memory` |
| Beta header | none (tool is GA on opus-4-7 / sonnet-4-6; verify per model in use) |
| Namespace root | `/memories` — ALL paths MUST begin with this prefix |

## 2. Required system-prompt preamble

The following instruction MUST be present in the system prompt when the memory tool is enabled (Anthropic auto-injects it in the API path; local replication injects at agent spawn):

```
IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE.
MEMORY PROTOCOL:
1. Use the `view` command of your `memory` tool to check for earlier progress.
2. ... (work on the task) ...
     - As you make progress, record status / progress / thoughts etc in your memory.
ASSUME INTERRUPTION: Your context window might be reset at any moment, so you risk losing any progress that is not recorded in your memory directory.
```

## 3. Commands — preconditions, postconditions, error modes

All error strings are VERBATIM from the Anthropic spec. Any backend returning a paraphrase is non-conforming.

### 3.1 `view`

| Aspect | Specification |
|---|---|
| Input | `{ command: "view", path: string, view_range?: [int, int] }` |
| Precondition | `path` begins with `/memories`; path resolves within memory root after canonicalization |
| Postcondition (directory) | Returns listing up to 2 levels deep, human-readable sizes, tab-separated, excluding dotfiles and `node_modules`; header line: `"Here're the files and directories up to 2 levels deep in {path}, excluding hidden items and node_modules:"` |
| Postcondition (file) | Returns contents with 1-indexed line numbers, 6-char right-aligned width, tab separator; header line: `"Here's the content of {path} with line numbers:"` |
| Postcondition (view_range) | Only the requested line range is returned, still with absolute line numbers |
| Error — path missing | `"The path {path} does not exist. Please provide a valid path."` |
| Error — file > 999999 lines | `"File {path} exceeds maximum line limit of 999,999 lines."` |
| Error — path traversal | reject before read; no partial output |
| Concurrency | safe with shared lock; atomic-rename writes guarantee no torn reads |

### 3.2 `create`

| Aspect | Specification |
|---|---|
| Input | `{ command: "create", path: string, file_text: string }` |
| Precondition | path under `/memories`; file does NOT already exist at path; parent directory exists or is auto-created |
| Postcondition | file exists with exactly `file_text` bytes; subsequent `view` returns identical content; operation is durable (fsync'd before return) |
| Success return | `"File created successfully at: {path}"` |
| Error — duplicate | `"Error: File {path} already exists"` |
| Concurrency | MUST use `O_CREAT \| O_EXCL` — exactly one concurrent caller wins, loser sees duplicate error |
| Atomicity | write to `<path>.tmp` → fsync → rename; no observable half-written file |

### 3.3 `str_replace`

| Aspect | Specification |
|---|---|
| Input | `{ command: "str_replace", path: string, old_str: string, new_str: string }` |
| Precondition | path exists as a file (not directory); `old_str` appears EXACTLY ONCE in file |
| Postcondition | file content = original with the single occurrence of `old_str` replaced by `new_str`; no other bytes modified |
| Success return | `"The memory file has been edited."` followed by a line-numbered snippet of the edited region |
| Error — path missing | `"Error: The path {path} does not exist. Please provide a valid path."` |
| Error — is directory | same as "path missing" |
| Error — not found | ``"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}."`` |
| Error — multiple matches | ``"No replacement was performed. Multiple occurrences of old_str `{old_str}` in lines: {line_numbers}. Please ensure it is unique"`` |
| Concurrency | read-modify-write — MUST serialize per-scope via `flock`; lock-read-compute-rename-release protocol; NO silent last-writer-wins |
| Atomicity | write-to-tmp + fsync + rename under lock |

### 3.4 `insert`

| Aspect | Specification |
|---|---|
| Input | `{ command: "insert", path: string, insert_line: int, insert_text: string }` |
| Precondition | file exists; `insert_line` ∈ [0, n_lines] (0 = before line 1) |
| Postcondition | `insert_text` inserted AT the specified line; all other bytes unchanged |
| Success return | `"The file {path} has been edited."` |
| Error — path missing | `"Error: The path {path} does not exist"` |
| Error — is directory | same as "path missing" |
| Error — invalid line | ``"Error: Invalid `insert_line` parameter: {insert_line}. It should be within the range of lines of the file: [0, {n_lines}]"`` |
| Concurrency | same serialization as `str_replace` |
| Atomicity | write-to-tmp + fsync + rename |

### 3.5 `delete`

| Aspect | Specification |
|---|---|
| Input | `{ command: "delete", path: string }` |
| Precondition | path under `/memories`; path exists (file or directory) |
| Postcondition | path does not exist after call; for directories, deletion is recursive |
| Success return | `"Successfully deleted {path}"` |
| Error — path missing | `"Error: The path {path} does not exist"` |
| Idempotency | Anthropic spec errors on missing — local implementations MUST follow this; DO NOT silently succeed on absent paths |
| Concurrency | exclusive lock on scope; safe after lock |

### 3.6a `search` (local extension — NOT in Anthropic `memory_20250818`)

Local-only verb for full-text retrieval across scope files. **Deterministic grep** — never semantic similarity. Semantic recall is a distinct tool surface (`cortex:recall`), invoked by the agent directly via MCP; memory-tool never aliases it.

| Aspect | Specification |
|---|---|
| Input | `search <query> [--scope <name>] [--limit N] [--regex]` |
| Precondition | `query` non-empty; if `--scope` given, scope exists and agent is in `readers` |
| Postcondition | Returns `<vpath>:<line>:<snippet>` one per match, up to `--limit` (default 50) |
| Filter | Results in scopes the agent cannot read are silently dropped (no leak) |
| Excludes | `.locks/`, `.audit.log`, `.registry.json` never scanned |
| Mode | `--regex` uses extended regex; default is fixed-string |
| Empty | Returns `"No matches for query in {root}."` |
| Error — denied | `"Error: agent '{id}' is not permitted to read scope '/memories/{name}'"` |

### 3.6 `rename`

| Aspect | Specification |
|---|---|
| Input | `{ command: "rename", old_path: string, new_path: string }` |
| Precondition | both paths under `/memories`; source exists; destination does NOT exist |
| Postcondition | source path no longer exists; destination path contains exactly the bytes of source |
| Success return | `"Successfully renamed {old_path} to {new_path}"` |
| Error — source missing | `"Error: The path {old_path} does not exist"` |
| Error — destination exists | `"Error: The destination {new_path} already exists"` — DO NOT overwrite |
| Atomicity | POSIX `rename(2)` — atomic within same filesystem |
| Concurrency | exclusive lock on BOTH source and destination scopes |

## 4. Universal invariants (apply to every command)

1. **Path confinement.** Every `path` MUST start with `/memories`. Before any filesystem operation, canonicalize the path (`realpath` / `pathlib.Path.resolve()`) and verify it remains within the memory root. Reject `../`, `..\\`, `%2e%2e%2f`, symlink escapes. Reject BEFORE I/O — no partial reads or partial writes on rejected paths.

2. **No cross-scope writes.** Writes from a scope's declared owner agents only (see `scope-registry.yaml`). Reader agents get read-only dispatch.

3. **Durability before return.** A success return implies `fsync(2)` has completed on the modified file AND on the directory containing it.

4. **Atomic observability.** Readers MUST never observe a partial write. Enforced by write-to-tmp + rename.

5. **Error messages are verbatim.** Implementations MUST return the exact strings specified in §3. Claude is trained on these strings; paraphrase degrades model behavior.

6. **No silent conversion.** If input violates precondition, return the defined error — never coerce (e.g., do not auto-create missing parent dirs on str_replace, do not trim `old_str` whitespace).

## 5. Substitutability rules (Liskov)

### 5.1 `view` ≠ semantic search ≠ `search`
Three distinct contracts, never aliased:
- **`view`** (FS, path-addressed): returns exact bytes or exact directory listing for the path given. Deterministic, reproducible.
- **`search`** (FS, content-addressed): returns exact line matches of a literal or regex query across scope files. Deterministic, reproducible. Implemented by this tool.
- **`cortex:recall`** (MCP, semantic): returns similarity-ranked entries based on embedding distance. Non-deterministic across index updates. Invoked separately via MCP — NOT routed through memory-tool.

A backend claiming `view` MUST return exact content — any similarity ranking belongs under `cortex:recall`. A backend claiming `search` MUST return explicit line matches — fuzzy/semantic behaviour is a contract violation.

### 5.2 `create` — no silent dedup
If a backend's underlying store performs deduplication (e.g., Cortex near-duplicate merging), `create` on that backend MUST surface the dedup as `"Error: File {path} already exists"`, never as silent success. Otherwise two backends that both return success will hold divergent state.

### 5.3 Authoritative backend designation
Local FS is authoritative for `create`, `str_replace`, `insert`, `rename`. Cortex MCP is an eventually-consistent replica, written asynchronously from a `.pending-sync` queue, never co-equal. A Cortex write failure MUST NOT cause a local operation to fail.

### 5.4 `rename` atomicity fallback
If a backend lacks an atomic `rename` primitive (e.g., vector stores), it MUST NOT claim to implement `rename`. The dispatcher routes `rename` only to local FS.

## 6. Size and quota caps

| Cap | Default | Source |
|---|---|---|
| Max bytes per file | 100 KB | developer recommendation (Anthropic: "Consider tracking memory file sizes"); we adopt as hard cap |
| Max files per scope | 2000 | aligned with Anthropic managed-agent store cap |
| Max total bytes per scope | 100 MB | aligned with Anthropic managed-agent store cap |
| Max line count per file | 999,999 | hard limit from `view` spec |
| Per-agent write budget | 5% of scope total (default) | from `scope-registry.yaml` entry |

Over-cap behavior: writes exceeding caps MUST fail with an explicit error, never truncate silently.

## 7. Security invariants

1. **Path traversal** — enforced per §4.1.
2. **Secret scrubbing** — PII/secret regex scan runs BEFORE write; matches block the write and append an entry to `~/.claude/memories/.audit.log` with reason.
3. **Quarantine namespace** — any memory derived from untrusted sources (PR bodies, issue text, web content) MUST be written under `/memories/quarantine/` and NEVER auto-loaded at spawn.
4. **Audit log** — every write appends one line to `~/.claude/memories/.audit.log`: `{iso8601, agent_id, scope, command, path, bytes, content_sha256, result}`. Append-only. Log write precedes payload write.

## 8. Context editing integration

The memory tool pairs with `clear_tool_uses_20250919` context-editing strategy (Anthropic server-side) or equivalent local compaction. Contract:

- Memory tool calls MUST be in the `exclude_tools` list so they survive clearing.
- Memory CONTENTS are eligible for prompt caching; the cache prefix remains valid across tool-use clearing iff memory bytes are unchanged.
- A local compaction hook MAY rewrite cleared tool outputs INTO memory, but that rewrite is itself a `create`/`str_replace` and MUST obey §3.

**Local policy deviation from Anthropic default**: we do NOT auto-compact-into-memory. Compaction is manual (human-reviewed). This is a deliberate fragility reduction (Taleb audit).

## 8a. Cortex replica queue (§5.3 implementation)

Every successful mutation (`create`, `str_replace`, `insert`, `delete`, `rename`) enqueues a JSON job to `$MEMORY_ROOT/.pending-sync/<ts>-<rand>.json` describing the post-state (including base64-encoded file contents for non-delete ops and a `content_sha256` digest). Enqueue failures do NOT fail the parent operation.

Queue commands:

| Command | Purpose |
|---|---|
| `memory-tool.sh sync-status` | Depth of queue (pending + claimed in-flight) and oldest job id |
| `memory-tool.sh drain-sync [--limit N]` | Atomically claims up to N jobs (rename-based, concurrent-safe) and emits them as JSONL. Claimed jobs no longer appear in subsequent drains. |
| `memory-tool.sh commit-sync <id>` | Deletes the claimed job after Cortex write succeeds. |
| `memory-tool.sh release-sync <id>` | Returns a claimed job to the queue (retry path on Cortex failure). |

Agent-facing drainer: `/session:memory-sync` (see `commands/session/memory-sync.md`). The Claude-side agent:
1. reads queue depth, 2. drains claimed jobs as JSONL, 3. calls `cortex:remember` via MCP per job, 4. commits on success / releases on failure. The CLI NEVER calls Cortex directly — the bash tool stays pure filesystem + Cortex interaction stays in the MCP-speaking agent.

**Invariant**: a claimed job is either committed, released, or manually recoverable at `$MEMORY_ROOT/.pending-sync/<id>.json.claimed`. Nothing is ever deleted without an explicit commit.

## 9. Hand-offs

| Concern | Agent |
|---|---|
| Concurrency protocol (flock, rename, version CAS) | Lamport |
| Governance schema (`scope-registry.yaml`, audit log, quotas) | Ostrom |
| Fragility audit (injection, poisoning, cascade) | Taleb |
| Effectiveness measurement (cache hit rate, recall precision, poisoning incidents) | Curie |
| Contract compliance test suite | test-engineer |
