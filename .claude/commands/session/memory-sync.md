# Drain Cortex Replica Queue

Replicate pending memory-tool writes to Cortex. Local FS remains the source of truth; this pushes the async replica so cross-session semantic recall stays in sync.

## Contract

See `memory/contract.md §5.3`. Local FS is authoritative; Cortex is an eventually-consistent replica. Each successful mutation by `memory-tool.sh` enqueues a job to `~/.claude/memories/.pending-sync/`. This command drains that queue by calling `cortex:remember` via MCP, then marks each job committed. Failures are released back to the queue for retry.

## Instructions

1. Check queue depth:

   ```bash
   tools/memory-tool.sh sync-status
   ```

   If "queue: empty" or "queue: 0 pending", stop and tell the user there is nothing to sync.

2. Drain up to 50 jobs (atomically claimed — a second concurrent drainer sees them as already in-flight):

   ```bash
   tools/memory-tool.sh drain-sync --limit 50 > /tmp/memsync-$$.jsonl
   ```

   Each line is a JSON job: `{id, ts, op, agent_id, scope, vpath, new_vpath?, bytes?, content_sha256?, content_b64?}`.

3. For each claimed job:
   - Base64-decode `content_b64` to get the post-op file contents (or skip for `op: "delete"`).
   - Call `mcp__plugin_cortex_cortex__remember` with:
     - `content`: the decoded contents (or a deletion marker `"__deleted__ <vpath>"` for deletes)
     - `tags`: `["memory-replica", "scope:<scope>", "agent:<agent_id>"]`
     - `agent_topic`: `<scope>` — the job's `scope` field verbatim. This maps to `agent_context` in Cortex's DB (see `mcp_server/handlers/remember.py:351`), enabling `agent_briefing.py` to filter memories by agent at SubagentStart.
     - `source`: `"memory-tool:<op>"`
     - Include `vpath`, `content_sha256`, and `ts` in the metadata so Cortex can deduplicate.
   - On success: `tools/memory-tool.sh commit-sync <id>`
   - On failure: `tools/memory-tool.sh release-sync <id>` (returns to queue for next drain)

4. Report to the user: N committed, M released, queue depth after.

## Rules

- **Local FS is authoritative.** Never re-read from Cortex and overwrite local files during a drain — this is a one-way replica.
- **Never retry indefinitely in this command.** If a job fails twice in the same drain, release it and move on; surface the failure in the report.
- **Quarantine jobs are not excluded.** Quarantine scope still replicates to Cortex but with the quarantine tag — Cortex consumers must honor the tag.
- **Do not drain if Cortex MCP is unavailable.** Check `mcp__plugin_cortex_cortex__memory_stats` (or any Cortex tool) first; if it errors, tell the user and stop — leaving jobs in the queue is the correct behavior.

$ARGUMENTS
