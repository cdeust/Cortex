# Native Claude and Codex shared-memory verification

On 22 September 2026, we verified bidirectional Cortex memory exchange between
installed Claude Code and Codex sessions on macOS. Each host retrieved a random
payload written by the other host. Neither read prompt contained the payload it
was supposed to retrieve.

| Check | Result |
| --- | --- |
| Claude writes; Codex recalls the exact payload | PASS |
| Codex writes; a fresh Claude session recalls the exact payload | PASS |
| Read prompts omit the other host's payload | PASS |
| Claude recall scoped to another project excludes the test record | PASS |
| Codex recall scoped to another project excludes the test record | PASS |

## Environment and procedure

The test used Claude Code 2.1.280, Codex CLI 0.155.1 and Cortex MCP 4.23.2,
with both hosts connected to the same PostgreSQL store. Two temporary project
directories supplied the positive and negative scope checks.

1. Claude stored a synthetic lookup key and random payload through its installed
   Cortex `remember` tool.
2. Codex stored its own synthetic record and used Cortex `recall` to retrieve
   Claude's payload using only the lookup key and project scope.
3. A fresh Claude session used Cortex `recall` to retrieve Codex's payload.
4. Both hosts repeated retrieval with the other project directory. Neither
   response included the synthetic test record.

The successful Codex session used `mcp_servers.cortex.required=true` as a
session-only startup setting. This requires Cortex initialization to succeed.
Persistent client configuration was not changed.

Cortex merged the similar synthetic records into memory 4369037 while retaining
both payloads. The record was soft-deleted after verification.

## Evidence

[trace.json](trace.json) contains the native tool names, arguments, test-record
response excerpts, blind read prompts, synthetic payloads and SHA-256 hashes of
the original local transcripts. Unrelated memories are excluded from the public
excerpts. Full transcripts remain private because they contain unrelated context.

The checks were recomputed from actual tool responses, rather than relying on the
hosts' final answers. The project-scope assertions concern the synthetic record;
they are not an authorization-boundary test.

## Native hook verification

After the user approved the updated Cortex 4.23.3 hook definitions, Codex's
native hook inventory confirmed all 12 Cortex handler entries as trusted. A
fresh Codex session received a `Cortex Memory Context` developer message through
its native SessionStart hook. A fresh Claude session also emitted a successful
SessionStart hook response containing Cortex context. Neither test prompt asked
the model to retrieve context through tools.

[hooks.json](hooks.json) records the context-delivery assertions and transcript
hashes. The installed Codex hook file matched the released repository artifact;
its SHA-256 was
`a25ce6d2358ebd72969483e5e051a1c54674c3e33be27ae4ed988239c5464f3a`.
The approved hashes were subsequently saved in the user's Codex configuration.

Codex requires renewed trust when a hook definition changes. The updated hooks
were awaiting approval before this check; that was not a failed execution.
The [Codex hook documentation](https://learn.chatgpt.com/docs/hooks) describes
review through `/hooks` and a startup warning for definitions requiring review.

These runs demonstrate native startup context on both hosts and shared memory
exchange in both directions on macOS. The interaction test used Cortex MCP
4.23.2; the follow-up Codex startup check exercised hook package 4.23.3.
