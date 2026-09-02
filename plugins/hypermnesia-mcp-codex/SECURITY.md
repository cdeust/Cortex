# Security Policy — Cortex plugin for Codex

This package is the Codex distribution of Cortex (`hypermnesia-mcp`). It
starts the published PyPI server over local stdio with the read-only or
idempotent-write `lean` tool profile. It installs no hooks, skills, apps or
agents, declares no remote endpoint and holds no secrets.

The security policy, supply-chain assurance (Sigstore build provenance, PEP 740
attestations, SBOM) and coordinated-disclosure process are shared with the
whole repository and live in the top-level
[SECURITY.md](https://github.com/cdeust/Cortex/blob/main/SECURITY.md).

## Reporting a vulnerability

Do not open a public issue. Send a private report through a
[GitHub security advisory](https://github.com/cdeust/Cortex/security/advisories/new).

## What this package accesses

- The local memory store: PostgreSQL at `DATABASE_URL` when configured,
  otherwise the zero-config SQLite file under `~/.claude/methodology/`
  (see [PRIVACY.md](https://github.com/cdeust/Cortex/blob/main/PRIVACY.md)).
- The `uvx` cache, to resolve the pinned `hypermnesia-mcp` release on first
  launch.

Nothing leaves the machine except the one-time model download described in
PRIVACY.md.
