# Security Policy — `cortex-viz` migration shim

This directory is the frozen, nonfunctional shim left behind when the
visualization plugin was renamed to `hypermnesia-mcp-viz`. It registers no
MCP server, no tools and no hooks beyond a session-start migration notice, so
it has no attack surface of its own.

Security reports for the visualization server go through its own repository,
[cdeust/cortex-viz](https://github.com/cdeust/cortex-viz/security/advisories/new);
reports for this repository go through the top-level
[SECURITY.md](https://github.com/cdeust/Cortex/blob/main/SECURITY.md).
Never open a public issue for a vulnerability.
