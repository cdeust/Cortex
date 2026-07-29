# Assurance Case

_Last updated: 2026-07-27, against v4.16.0._

An assurance case is an argument, with evidence, that a system's security
requirements are met — and an honest statement of where the argument stops.
This document is the security argument for Cortex: what it is required to
protect, what it is exposed to, the design principles it applies, the common
implementation weaknesses it counters, and what it explicitly does **not**
claim. [SECURITY.md](../SECURITY.md) covers reporting and supply chain;
[PRIVACY.md](../PRIVACY.md) covers data handling.

## 1. Security requirements — what a user can and cannot expect

**R1 — Memory content stays on the machine.** No memory, transcript, profile
or wiki page is transmitted anywhere by default. The only outbound traffic is
the one-time model download from Hugging Face, plus integrations the user
configures explicitly (a remote `DATABASE_URL`, an upstream MCP server, an
OTLP endpoint). Metrics exported over OTLP, when opted in, are counts and
latencies — never content.

**R2 — The artifact you run is the artifact that was published.** Every
release carries a Sigstore build-provenance attestation and a published
SHA-256, verifiable before install (SECURITY.md § Supply-chain assurance).

**R3 — Untrusted text cannot reach the database as code.** Content arriving
from transcripts, ingested documents, upstream MCP servers or the model is
data. It is stored and retrieved; it never becomes SQL, a shell command, or an
imported module.

**R4 — Well-known secret shapes are scrubbed on the automatic capture path.**
Connection-string passwords, API-key shapes and tokens are masked before an
auto-captured tool result is persisted.

**R5 — A single tool call cannot exhaust the host.** Responses are bounded,
queries are limit-capped, and network reads carry timeouts.

**What a user must NOT expect:** Cortex is not a sandbox. It runs with the
user's own permissions, by design, because its job is to read the user's
session history and source trees. It cannot defend against a compromised host
process, a malicious Claude Code plugin running beside it, or a user who
stores a credential in a memory deliberately. It performs no authentication of
its own — the trust decision is the decision to install it.

## 2. Threat model

| # | Adversary / source | Capability assumed | Concern |
|---|---|---|---|
| T1 | Tampered distribution | Publishes a modified wheel, `.mcpb` or marketplace pin | Full keylogger over the user's engineering work (SECURITY.md states this plainly) |
| T2 | Hostile content in ingested material | Controls the text of a transcript, `.docx`, Confluence export, or an upstream MCP server's response | Injection into SQL or the filesystem; poisoning what is later recalled |
| T3 | Malicious wiki query block | Authors a `cortex-query` view in a wiki page | Reading tables or columns the view mechanism was not meant to expose |
| T4 | Compromised dependency | Ships a malicious version of a transitive package | Arbitrary code in-process (the ML stack is the bulk of this surface) |
| T5 | Local disclosure | Reads files on the same machine | Secrets captured into the store, or a password echoed in a log |
| T6 | Resource abuse | Sends a pathological query or an enormous document | Unbounded response, unbounded memory, a hung call |

Out of scope, stated rather than silently assumed: an attacker who already
executes code as the user (T1's outcome is the same as owning the account); a
malicious MCP *host*; and physical access to the machine.

## 3. Trust boundaries

Data or execution changes trust level at exactly these five places:

1. **Host → server (stdio).** Tool arguments arrive from the MCP host. Each
   tool declares a typed signature and schema; FastMCP rejects arguments that
   do not match before any handler runs, and
   `mcp_server/validation/schemas.py` adds a second per-tool check on the
   tools it covers. This is the *only* control channel: Cortex opens no
   socket and listens on no port.
2. **Filesystem → server.** Session transcripts under `~/.claude/`, source
   trees the user points at, and ingested documents. All are parsed as data;
   `infrastructure/document_reader.py` isolates the reading, the parsers
   (`core/docx_parser.py`, `core/confluence_parser.py`) are pure and
   stdlib-only, and a malformed container fails loudly and writes nothing.
3. **Server → store.** SQLite file or PostgreSQL. Every value crosses as a
   bound parameter; every identifier that must be interpolated comes from an
   in-code allowlist (§5).
4. **Server → network.** The one-time model download, plus user-configured
   endpoints. HTTPS with the platform's default certificate verification;
   no code path disables it.
5. **Store → host (recall).** Retrieved memories are returned to the model as
   text. Cortex does not, and cannot, guarantee that text is benign — it is
   whatever was captured. This is the boundary where prompt-injection risk
   lives, and §6 states the limit.

## 4. Secure design principles applied

Following Saltzer & Schroeder (1975), applied concretely rather than cited
decoratively:

- **Least privilege / no ambient authority.** No network listener, no
  privileged install step, no daemon. The default backend is a single local
  file. Destructive tools (`forget`, `wiki_purge`, `wiki_migrate`) are
  *rejected on call* under the `lean` profile, not merely hidden from
  `tools/list` — hiding a tool while still executing it would be a hole
  (`mcp_server/tool_profile_middleware.py`).
- **Fail-safe defaults.** Local SQLite by default; telemetry export off until
  an environment variable is set; a malformed document ingest writes nothing
  rather than a partial page; an unreachable PostgreSQL degrades to the local
  store with an explicit warning rather than silently dropping writes.
- **Complete mediation.** Every tool call passes the same middleware chain and
  the same schema validation; there is no side entrance to the store.
- **Economy of mechanism.** One write path (`remember`/`wiki_write`), one
  retrieval path (WRRF fusion), one ingestion seam (`ParsedDocument` →
  normalizer). New adapters swap the byte source, not the pipeline.
- **Separation of concerns as a security property.** The layer rule (`core`
  imports only `shared` and the stdlib; `infrastructure` never imports
  `core`) keeps all I/O — and therefore all boundary crossings — in modules
  that can be audited as a set.
- **Defence in depth on the supply chain.** Pinned actions by SHA, Trusted
  Publishing (no long-lived PyPI token exists to steal), Sigstore attestation,
  published checksums, an SBOM per release, and a consumer-side verifier
  (`scripts/verify_release_artifact.py`).

## 5. Common implementation weaknesses, and how each is countered

| Weakness (CWE) | Counter | Evidence |
|---|---|---|
| SQL injection (CWE-89) | Values are bound parameters; interpolated identifiers come from allowlists — `_TABLE_WHITELIST` / `_COLUMN_WHITELIST` gate table, projection and `WHERE` columns, and an unknown name is refused rather than escaped | `mcp_server/core/wiki_view_executor.py`, `mcp_server/infrastructure/pg_store*.py` |
| OS command injection (CWE-78) | Cortex builds no shell command from ingested or recalled content | CodeQL default suite, 0 open alerts |
| Code injection / unsafe deserialization (CWE-94, CWE-502) | No `eval`, no `exec`, no `pickle` of untrusted data; documents are parsed with stdlib `zipfile`/`xml.etree` into a typed model | `core/docx_parser.py`, `core/confluence_parser.py` |
| Path traversal (CWE-22) | Store and artifact paths are derived from configuration and content hashes, not from ingested text | `infrastructure/config.py`, `infrastructure/artifact_store.py` |
| Secret exposure in logs/store (CWE-532) | Structural URL password masking plus conservative secret-shape scrubbing on the auto-capture path | `mcp_server/shared/redaction.py`, wired in `hooks/post_tool_capture.py`; GitHub secret scanning reports 0 open alerts |
| Improper input validation (CWE-20) | Typed tool signatures at the boundary; per-tool schemas; query limits clamped to a maximum | FastMCP registration, `mcp_server/validation/schemas.py` |
| Uncontrolled resource consumption (CWE-400) | Priority-weighted response budget, capped query limits, per-test and network timeouts | `core/response_budget.py`, `_MAX_LIMIT` in the view compiler, `_REQUEST_TIMEOUT` in `infrastructure/pipeline_install_release.py` |
| Memory-safety classes (CWE-119 family) | Not reachable: pure Python, no C extension authored by this project | — |
| Vulnerable dependencies (CWE-1395) | Dependabot alerts and automated security fixes enabled (verified via the GitHub API, 2026-07-27, 0 open alerts); CycloneDX SBOM per release | `.github/workflows/release.yml` |

Standing analysis: CodeQL default setup (Python, JavaScript/TypeScript,
Actions) on every push and pull request plus weekly, currently 0 open alerts;
OpenSSF Scorecard via `.github/workflows/scorecard.yml`; and 6439 tests run on
four Python versions, two backends and Windows.

## 6. What this assurance case does NOT claim

- **It does not claim freedom from defects.** Provenance proves who built an
  artifact, not that the source is correct.
- **It does not claim protection against prompt injection through recalled
  content.** A memory captured from a hostile document is returned as text to
  a model that may act on it. Mitigating that belongs to the host's tool-use
  policy; Cortex's contribution is provenance on ingested pages so a suspect
  source can be traced and purged.
- **The test suite is not yet strong enough to carry this argument alone.**
  Statement coverage is 82.02% (measured in the CI coverage job, run
  30316539703, 2026-07-28) and is held by a `--cov-fail-under=82` floor in
  that job, but coverage proves execution, not detection: mutation testing
  is wired for one module rather than the load-bearing set (the changed
  code of #196 was mutation-triaged to zero non-equivalent survivors;
  the pre-existing condensers backlog is
  [#228](https://github.com/cdeust/Cortex/issues/228)). Raising mutation
  strength across the load-bearing set remains item 1 on
  [ROADMAP.md](ROADMAP.md).
- **Pyright `strict` is not the operating mode.** The build type-checks at
  `standard` with **zero diagnostics** (568-diagnostic backlog burned down,
  issue #197, 2026-07-28) and ruff enforces an explicit, broadened rule set
  (`E4/E7/E9/F/S110/BLE001/PLR2004/E501/PLC0415/S608`, each finding fixed or
  carrying a per-site named mechanism) — that is the "maximally strict, where
  practical" posture. `strict` mode remains out of reach: it reports 10,231
  errors, ~9,300 of them the Unknown-type family, which is an
  annotation-coverage project rather than a configuration change (measured,
  issue #197).
- **No dynamic analysis is performed.** There is no fuzzer and no sanitizer
  run; the language removes the memory-safety motivation for one, but that is
  an argument about a class of bug, not a substitute for the technique.
- **`.mcpb` and marketplace installs consume the git tree or bundle
  directly**, so their integrity is the tagged commit and its attestation,
  not a downloaded checksum a user verified.
