# Security Policy — `cortex` migration shim

This directory is the frozen, nonfunctional shim left behind when the plugin
was renamed to `hypermnesia-mcp` (v4.15.0). It registers no MCP server, no
tools and no hooks beyond a session-start migration notice, so it has no
attack surface of its own.

Security reports for the product it points to go through the repository's
top-level [SECURITY.md](https://github.com/cdeust/Cortex/blob/main/SECURITY.md):
open a [private GitHub security advisory](https://github.com/cdeust/Cortex/security/advisories/new),
never a public issue.
