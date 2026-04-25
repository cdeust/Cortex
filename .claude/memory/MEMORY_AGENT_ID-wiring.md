# MEMORY_AGENT_ID Wiring Contract

**Status**: design document. Implementation deferred to refactorer.
**Binding on**: every script that spawns a subagent process.

---

## 1. Where MEMORY_AGENT_ID MUST be set

`MEMORY_AGENT_ID` is the identifier recorded in the audit log and consulted by the ACL check in `memory-tool.sh`. It MUST be exported before any process that may invoke `memory-tool.sh` — directly or transitively.

The following spawn sites currently exist. Each MUST be updated:

| Script | Spawn mechanism | Status |
|---|---|---|
| `scripts/spawn-agent.sh` | `exec claude --append-system-prompt ...` | MISSING |
| `scripts/test-spawn-agent.sh` | spawns via `spawn-agent.sh` (test shim) | inherits from spawn-agent.sh |
| `tools/worktree-manager.sh` | `git worktree add` + `git` commands only | N/A — does not spawn claude |

Additional spawn surfaces to check when adding new tooling:
- Any script that calls `claude -p` or `claude --append-system-prompt`.
- Any script that calls `tools/memory-tool.sh` directly on behalf of a named agent.

---

## 2. How to extract the agent slug from the agent definition file

Agent definition files live at `agents/<slug>.md` or `agents/genius/<slug>.md`.

The slug is the file basename without the `.md` extension:

```bash
# Given: AGENT_FILE="$REPO_ROOT/agents/engineer.md"
AGENT_SLUG="$(basename -- "$AGENT_FILE" .md)"
# Result: "engineer"
```

The frontmatter `name:` field MUST equal the slug. If the two diverge, the slug (filename) wins — it is the stable identifier used in the registry and ACL.

To verify slug = frontmatter name (for auditing purposes, not required at spawn time):

```bash
FRONTMATTER_NAME="$(awk '/^---$/{f++; next} f==1 && /^name:/{gsub(/^name:[ ]*/, ""); print; exit}' "$AGENT_FILE")"
[[ "$FRONTMATTER_NAME" == "$AGENT_SLUG" ]] || echo "WARNING: slug/name mismatch in $AGENT_FILE"
```

---

## 3. The spawning contract

Every agent-spawning script MUST:

```
INVARIANT: export MEMORY_AGENT_ID=<slug> immediately before exec'ing the agent process.
```

Concretely, for `scripts/spawn-agent.sh`, the following lines MUST be added immediately before the `exec claude ...` calls:

```bash
# Set MEMORY_AGENT_ID so memory-tool.sh audit log and ACL use the correct identity.
export MEMORY_AGENT_ID="$AGENT"   # AGENT = slug derived from AGENT_FILE basename
```

For scripts that spawn agents in subshells or via `env(1)`, pass it explicitly:

```bash
env MEMORY_AGENT_ID="$AGENT_SLUG" claude --append-system-prompt "$AGENT_BODY" -p "$TASK"
```

For worktree-based spawns where the agent runs in a separate shell, set the variable in the worktree's environment before handing control:

```bash
export MEMORY_AGENT_ID="$AGENT_SLUG"
exec claude ...
```

---

## 4. Default and fallback

`memory-tool.sh` already defaults `MEMORY_AGENT_ID` to `"unknown"` when unset:

```bash
MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-unknown}"
```

Any audit log entry with `agent_id=unknown` indicates a spawn site that has not yet been updated. The `memory-tool.sh audit` command will surface these as `agent=unknown` in the top-agents-by-byte summary — use that to identify gaps.

---

## 5. ACL implications

The `scope-registry.json` `owners` list references agent slugs directly (e.g., `"engineer"`, `"architect"`). If `MEMORY_AGENT_ID` is not set, all writes from that agent will be attributed to `"unknown"`, which:

- Will fail scope ACL checks if `owners` does not include `"unknown"` or `"*"`.
- Will make the audit trail untrustworthy (all writes from all unidentified agents pooled together).

Both are contract violations per `memory/contract.md §7`.

---

## 6. Refactorer checklist

When applying this contract:

1. Edit `scripts/spawn-agent.sh`: add `export MEMORY_AGENT_ID="$AGENT"` before both `exec claude` branches.
2. Verify `scripts/test-spawn-agent.sh` records `MEMORY_AGENT_ID` in the shimmed `claude` argv or environment — update the shim's assertions accordingly.
3. Grep for any new `exec claude` or `claude -p` invocations added since this document was written and apply the same pattern.
4. Run `scripts/test-spawn-agent.sh` and verify all tests pass.
5. Run a smoke test: spawn engineer, write a file, run `memory-tool.sh audit` and confirm the entry shows `agent=engineer`, not `agent=unknown`.
