# ADR-0788: scripts/verify_mcp_hosts.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/verify_mcp_hosts.py`; original SHA-256 `a29f5104dccd83430e2104034223253c5a3ada5d0caeec4d473509584c08f9f8`.

## Original docstring, lines 2–21

````text
"""Exercise Cortex's hook-free stdio contract as common MCP hosts.

This is a protocol smoke test, not a mocked FastMCP/MCP-SDK unit test. Each
case starts the production entry point as a child process, sends a complete
MCP lifecycle batch, and verifies discovery plus one real SQLite-backed tool
call. Client names are deliberately varied: Cortex must not branch on
Claude-specific host identity, environment, or hooks.

Behaving *as a host* is load-bearing, not decorative: the exchange itself
lives in `mcp_host_client.py`, which keeps stdin open until every expected
response has arrived and closes it only then. Closing stdin is the MCP
shutdown signal (2025-06-18 §Lifecycle › Shutdown › stdio), so the previous
`subprocess.run(input=...)` shape signalled shutdown before reading a single
response and then demanded answers the protocol never owed it -- see that
module's docstring for the mcp 2.0.0 interleaving where the demand is
actually refused, in silence.

Environment isolation (PYTHONPATH stripping, the SOCKS regression fixture,
storage selection) also lives there, in `environment()`.
"""
````

## Original comment, lines 57–58

````text
# source: tests_py/test_main.py standalone baseline plus its three documented
# optional upstream integrations (ingest_codebase, change_impact, ingest_prd).
````

