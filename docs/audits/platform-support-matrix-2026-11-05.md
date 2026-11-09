# Platform support matrix, measured cells only (2026-11-05)

Issue #730, slice 1: enumerate the supported combinations of OS and architecture,
host client and version, backend and install channel, and label every cell that no
receipt measures. This document makes no support claim. A cell is **measured** only
when a committed or published receipt names it; everything else is **not measured**,
even where the code is designed to work.

Base: `main` at `8ef48137` (Pipeline run
[42058911839](https://github.com/cdeust/Cortex/actions/runs/42058911839), green).
Owner scope (issue #730, October 10): this workspace qualifies macOS and native
Claude/Codex; Windows is verified by the owner's collaborator under the same
contract; Linux qualification is deferred and does not block a macOS release.

## Evidence levels

| Level | What it proves | What it does not prove |
| --- | --- | --- |
| **N, native journey** | A real installed host (Claude Code, Codex) ran its own lifecycle events against Cortex; the receipt names host versions and checks. | Any combination not named in the receipt. |
| **P, CI install probe** | `scripts/install_e2e/run.py` on a clean runner: the real Claude Code CLI installs the plugin from the checkout, `claude --init-only` runs Setup and SessionStart under the host timeout, the host connects the MCP server, `remember` then `recall` returns the token, a second session says "Cortex ready". | Codex; compaction, subagents, edit gates, SessionEnd; cross-host transfer; project exclusion; a published artifact (the probe installs the checkout). |
| **L, backend lifecycle** | The managed PostgreSQL tree starts, loads `vector` and `pg_trgm`, is shared by a second process and stops (ADR-1114, measured 2026-10-17 and 2026-10-28). | Any host journey. |
| **U, unsupported by design** | The code refuses the combination and names the cause. | — |
| **—, not measured** | No receipt found in `docs/verification/`, `docs/adr/` or the release assets. | — |

## Native host journeys (level N)

| # | OS / arch | Hosts | Cortex / channel | Backend | Checks with a receipt | Receipt |
| --- | --- | --- | --- | --- | --- | --- |
| N1 | macOS, arch not recorded | Claude Code 2.1.280, Codex CLI 0.155.1 | 4.23.4, Claude plugin + Codex plugin | shared local PostgreSQL | Claude→Codex and Codex→Claude blind transfer; project exclusion on both hosts; reader prompts omit the target payload; automatic startup context on both hosts; 12 persisted trusted hook entries | release asset `native-host-verification-4.23.4.json`, sha256 `6e30b48139d4d2206e21a07a64f9d9affaa59f991f7f5d8d27d9e83d987248de` (matches the published `.sha256`) |
| N2 | macOS, arch not recorded | Claude Code 2.1.280, Codex CLI 0.155.1 | 4.23.2 MCP; hook package 4.23.3 (Codex), 4.23.2 (Claude) | shared PostgreSQL | the same transfer and exclusion checks; native startup context on both hosts; 12 Cortex hook entries trusted in Codex | `docs/verification/claude-codex-handoff-2026-09-22/` |
| N3 | macOS arm64 | Codex 0.154.0 | 4.23.2 pinned wheel | explicit SQLite scratch | child briefing delivery; file-cue heat priming (project-scoped); one SessionEnd log entry and receipt, no pending job | `docs/verification/codex-native-4.23.2.md` |
| N4 | macOS ARM | Codex CLI 0.160.0 | 4.23.5 hooks | PostgreSQL | 28 hook definitions trusted across four plugins, 11 of them Cortex hooks; SessionStart, UserPromptSubmit, PostToolUse and SessionEnd completed natively | `docs/verification/codex-hooks-20261002.md` |

N1 and N3 ran a published artifact: N1 the 4.23.4 plugins; N3's follow-up the published
4.23.2 wheel (all 659 runtime Python files matched `c8827be`), where briefing delivery
and SessionEnd passed but file-cue priming did not (the memory stayed at 0.3, #629). Only
N2 records a digest of what ran: the installed Codex hook file matched the released
artifact, sha256 `a25ce6d2358ebd72969483e5e051a1c54674c3e33be27ae4ed988239c5464f3a`. No
receipt binds every check to the digest of the artifact it ran (issue #730, last
acceptance item, and #729).

## CI install probe and environment check (level P), run 42058911839

| Runner image | Host | Channel | Backend reached | Install probe | Environment check |
| --- | --- | --- | --- | --- | --- |
| `ubuntu-26.04` (ubuntu-latest) | Claude Code 2.1.306 | Claude plugin from the checkout | managed PostgreSQL | pass | pass |
| `macos-26-arm64` (macos-latest) | Claude Code 2.1.306 | Claude plugin from the checkout | managed PostgreSQL | pass | pass |
| `windows-2025-vs2026` (windows-latest) | Claude Code 2.1.306 | Claude plugin from the checkout | SQLite, printed as `SQLite fallback: managed PostgreSQL unavailable here (native Windows …)` | pass | pass |

The probe report of each install job has `hook_within_timeout`, `hook_installed_nothing`,
`mcp_connected_by_host`, `remember_recall`, `recall_contains_token` and
`no_process_left` true (job logs 127365155597, 127365155717, 127365155861). The
logs do not print the CPU: the Ubuntu and Windows rows are x64 by GitHub's runner
label, not by a measurement in the log.

## Backend lifecycle (level L) and unsupported cells (level U)

From ADR-1114 (Consequences): the managed server is measured on macOS arm64 and
x86_64 under Rosetta, Ubuntu 26.04 on both CPUs, Ubuntu 24.04 and Debian 12 on
aarch64. Unsupported by design, SQLite with a recorded fallback cause: native
Windows, musl, Linux GNU with glibc older than 2.36 (Ubuntu 22.04, RHEL/Rocky/Alma 9),
other CPUs.

## Matrix

Rows: OS and architecture. Columns: host and install channel. A cell lists the
evidence levels above; `—` is not measured.

| OS / arch | Claude Code plugin, SQLite | Claude Code plugin, managed PostgreSQL | Codex plugin, SQLite | Codex plugin, PostgreSQL | Claude Desktop `.mcpb` | Cowork | `uvx hypermnesia-mcp` (PyPI) | Docker |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| macOS arm64 | — | P, L | N3 (pinned wheel, manifest hook commands) | N4 (N1, N2 arch not recorded) | — | — (#741) | — | — |
| macOS x86_64 | — | L (Rosetta) | — | — | — | — | — | — |
| Linux x86_64, glibc ≥ 2.36 | — | P, L | — | — | — | — | — | e2e job: the container lists at least 57 tools (`scripts/docker_smoke.sh`), not a host journey |
| Linux aarch64, glibc ≥ 2.36 | — | L | — | — | — | — | — | — |
| Linux, glibc < 2.36 or musl | — | U | — | U | — | — | — | — |
| Windows x86_64 | P | U | — | U | — | — | — | — |

Remote or team PostgreSQL (a configured `database_url`): no native receipt.

## Acceptance items of #730 with no receipt on any platform

- Actual compaction and recovery: PreCompact was not triggered natively (N4 report,
  "PreCompact, edit gates and subagent events were not triggered").
- Hook trust state outside macOS Codex (N1, N2, N4).
- Unicode payloads, dependency failure and clean teardown in a native host.
- Tool outputs after SDK conversion in each client, including empty and error results.
- Support claims gated on receipts tied to artifact digests.

## Remaining slices of #730

1. A receipt schema that binds each native check to the artifact digest it ran
   (shared with #729, which names the running artifact and its digest). Delivered:
   `cortex-native-receipt/1`, validated by `scripts/native_receipt.py`.
2. A gate that refuses a support claim (README, release notes) for a cell without a
   current receipt of that schema.
3. Native receipts for the cells marked `—` that the owner's scope requires: Windows
   (collaborator), then macOS x86_64 and the `.mcpb` channel.
