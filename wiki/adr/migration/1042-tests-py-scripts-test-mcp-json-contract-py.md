# ADR-1042: tests_py/scripts/test_mcp_json_contract.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/scripts/test_mcp_json_contract.py`, original SHA-256 `aec09ec6efd52a5a9aa3acb9d73e1295bd21c219f2bba0e01519ef5557feca8b`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–43

````text
"""Contract test for the plugin MCP server config — the plugin↔Claude-Code interface.

Verifies the inline `mcpServers` object in `.claude-plugin/plugin.json`
against the documented Claude Code plugin contract.
Source: https://code.claude.com/docs/en/plugins-reference,
section "Environment variables":

  > ${CLAUDE_PLUGIN_ROOT}: ... Both are substituted inline anywhere they
  > appear in skill content, agent content, hook commands, monitor
  > commands, and MCP or LSP server configs.

And the canonical example in the same reference:

  "plugin-database": {
    "command": "${CLAUDE_PLUGIN_ROOT}/servers/db-server",
    "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"],
    "env": { "DB_PATH": "${CLAUDE_PLUGIN_ROOT}/data" }
  }

History of this contract:

Discord 2026-05-09: prior config used a Python `-c` one-liner that
read ~/.claude/plugins/installed_plugins.json and execvp'd into the
launcher. Failure modes were silent because `python3 -c` swallowed stack
traces. The fix routes through the documented substitution mechanism.

2026-06-12: the config moved from a repo-root `.mcp.json` (referenced by
plugin.json as "./.mcp.json") to an inline object in plugin.json. Reason:
Claude Code ALSO interprets a repo-root `.mcp.json` as PROJECT-scoped MCP
config when the plugin source repo itself is opened as a working
directory. In project scope `${CLAUDE_PLUGIN_ROOT}` is never substituted
(it is plugin-scope only), so the spawn ran
`python3 '<repo>/${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py'` → ENOENT →
"MCP error -32000: Connection closed" on every session in this repo,
shadowing the healthy plugin-scoped server. Inline plugin.json
`mcpServers` is documented and is invisible to project-scope discovery.

This test guards against regression to either failure mode: the inline
`-c` script (substitutability violation: it imposed a STRONGER
precondition than the contract — a specific marketplace key in
installed_plugins.json) and the reintroduction of a repo-root
`.mcp.json`.
"""
````

