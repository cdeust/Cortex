# Memory Audit

Surface the audit trail for memory-tool writes, ACL denials, byte volume by agent, and any anomalies (write storms, cross-scope agents, denial sequences).

## Contract

See `memory/contract.md §7.4`. The audit log at `$MEMORY_ROOT/.audit.log` is append-only. Every write, ACL denial, and TTL expiration emits one tab-delimited line:

```
{iso8601}  {agent_id}  {scope}  {command}  {vpath}  {bytes}  {sha256}  {result}
```

This command reads that log and surfaces anomalies. It is read-only — it never modifies memory state.

## Instructions

1. Run the audit for the last 24 hours:

   ```bash
   tools/memory-tool.sh audit
   ```

   To narrow the window:

   ```bash
   tools/memory-tool.sh audit --since 2026-04-23T00:00:00Z
   ```

2. Read and relay the output sections to the user:

   - **Audit log** — raw entries (timestamp, agent, scope, command, result, path).
   - **Summary** — total writes, ACL denials by agent+scope, top 5 agents by byte volume, files within 10% of their scope's `max_file_kb` limit.
   - **Anomalies** — flag any of the following:
     - Any scope with >50 writes in a rolling 1-hour window.
     - Any agent writing to >3 different scopes in the window.
     - Any sequence of ≥5 consecutive `acl_denied` results from the same agent (possible prompt-injection poisoning attempt).

3. If anomalies are detected, surface them prominently and recommend:
   - For write storms: check if an agent is looping or retrying in error.
   - For cross-scope writes: verify the agent has curator clearance.
   - For denial sequences: consider quarantining the agent's output and running `memory-tool.sh search` to inspect what it was attempting to write.

4. If the audit log is empty or does not exist, tell the user no writes have been recorded yet.

## Rules

- **Never modify memory during audit.** This command is observation only.
- **Do not relay raw SHA256 hashes unless the user asks.** They are noise in normal audit summaries.
- **Surface anomalies before the summary** if any are present — anomalies are the highest-priority output.

$ARGUMENTS
