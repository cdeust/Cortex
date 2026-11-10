# Scheduled groomer (G-3) — installation and operation

Increment G-3 of the "grooming continu" program (design doc:
`scratchpad/grooming-continu-design.md` §4 Incrément 3). Depends on **G-1**
(headless write-path governance — `mcp_server/handlers/consolidation/
headless_authoring.py`'s `claude -p` children write only through
`wiki_write.write_governed_page`, never a raw disk write) and **G-4**
(`get_grooming_health` — the backlog/staleness signal this script reads).

## What runs

`scripts/groomer.py` is the entry point. It:

1. Reads `get_grooming_health` (backlog count + staleness age for the
   `wiki` and `distillation` legs).
2. Decides which legs are **due** (`core.grooming_health.legs_due` — stale
   AND non-empty backlog; `--force` overrides for manual runs).
3. Drains the wiki leg via the existing `headless_authoring` cycle
   (curation-gap file docs + missing anchor pages — text-generation by
   `claude -p`, write by this process through the G-1 governed path).
4. Drains the distillation leg via `curate_distill`'s ready-built prompts
   (`handlers/consolidation/distill_drain.py`) — here the `claude -p`
   *child* calls `remember` itself over MCP, using
   `curate_distill.build_distill_prompt`'s exact required call shape
   (INC7.8/M-D8), unmodified except for an advisory reminder appended at
   the end.
5. **Never runs `lesson_promotion`.** Its backlog count is read (a plain
   `COUNT(*)`, not the promotion handler — see `get_grooming_health.py`)
   and reported in the journal only, for a human to act on in an
   interactive session. `lesson_promotion.handler` is never imported by
   this script or by any module it calls
   (`test_groomer_never_calls_lesson_promotion` greps this at test time).

## Dry-run vs apply

**Dry-run is the default.** Running `scripts/groomer.py` with no flags
only calls READ_ONLY handlers (`get_grooming_health`, and — if the
distillation leg is due — a bounded `curate_distill` preview call) and
writes a journal describing what it *would* do. Nothing is written to the
wiki or the memory store.

```bash
uv run python scripts/groomer.py
```

`--apply` executes the due legs and additionally requires
`CORTEX_HEADLESS_AUTHORING=1` set in the environment (the same opt-in gate
`wiki_maintenance._headless_authoring_enabled` already uses) — the script
refuses to write without it, even with `--apply` passed:

```bash
CORTEX_HEADLESS_AUTHORING=1 uv run python scripts/groomer.py --apply
```

## Budget

No new budget knobs are introduced. The script reuses the existing,
already-measured `CORTEX_HEADLESS_*` environment variables
(`headless_authoring.py`):

| Variable | Default | Applies to |
|---|---|---|
| `CORTEX_HEADLESS_CONCURRENCY` | 4 | both legs (in-flight `claude -p` cap) |
| `CORTEX_HEADLESS_BUDGET_SEC` | 300 | both legs, independently (wall-clock cap **per leg**) |
| `CORTEX_HEADLESS_USD_BUDGET` | 5.0 | both legs, independently (USD cap **per leg**) |
| `CORTEX_HEADLESS_MAX_FILE_DRAINS` | 8 | wiki leg (file-doc gaps) |
| `CORTEX_HEADLESS_MAX_ANCHOR_DRAINS` | 8 | wiki leg (anchor pages) |
| `--distill-limit` (script flag, not env) | 5 | distillation leg — reuses `curate_distill.handler`'s own existing default, not a new number |

Worst case per `--apply` run: 8 + 8 wiki calls + 5 distillation calls = 21
`claude -p` invocations, up to $5 + $5 = $10, up to 300s + 300s ≈ 10
minutes wall-clock (the two legs run sequentially, each under its own
`CycleBudget`). This is consistent with the design doc's own §3(a)
estimate ("15-25 appels claude -p, ≈5-10 USD/run") — not a fresh
extrapolation. **Measure the first few real dry-runs' `jobs_offered`
counts and the first real `--apply` run's `usd_spent` before trusting this
ceiling in production**; the design doc explicitly flags this as unmeasured
until exercised (§3(a), "Ce chiffre doit être mesuré empiriquement au
premier dry-run").
`usd_spent` sums only the costs the CLI reported; a call that reported none
(non-zero exit, timeout, non-JSON output, absent `total_cost_usd`) is counted
in `unpriced_calls` instead, so `usd_spent` is a lower bound whenever
`unpriced_calls` > 0 (#733).

## Active-session guard

Before writing anything, `--apply` calls
`mcp_server.infrastructure.session_registry.has_active_session_window()`.
If any interactive Claude Code window has a live, non-tombstoned session
registered, the run is **skipped entirely** (not queued, not blocked —
skipped; the next scheduled run will re-check) and the journal records
`active_session_guard`. This avoids a headless `claude -p` child competing
for the same DB/attention as a human working session — the guard is a
coarse liveness check (any live registered window with a session_id), not
the stricter pid-lineage check `current_window_session()` uses for
per-window attribution (see the function's docstring for why the coarser
check is the right one here).

## Known scope gap — wiki staleness signal vs. wiki leg's actual queue

The `wiki` leg's due/not-due decision reads `get_grooming_health`'s `wiki`
staleness, itself sourced from `curate_wiki`'s cluster/coverage/reauthor
backlog (`total_clusters_eligible`). The leg this script actually runs —
`headless_authoring.run_headless_authoring_cycle` — drains a *different*
queue: pages carrying `curation_gaps` frontmatter and missing anchor
pages. These are not the same job set. A "wiki is stale" alarm does not
guarantee the wiki leg finds anything to drain, and a successful wiki-leg
run does not shrink `curate_wiki`'s cluster backlog. Extending
`headless_authoring` to also drain `curate_wiki`'s cluster/coverage/
reauthor jobs (the design doc's original, larger sketch for this
increment) is explicitly out of scope here — G-3 reuses the existing
G-1-governed mechanism as-is. Do not assume the staleness alarm and the
leg's actual output are tightly coupled until this gap is closed in a
future increment.

## Journal

Every run (dry-run or apply) writes `docs/campaigns/g3_groomer_<mode>_
<UTC-timestamp>.json` and a companion `.md` summary — same pattern as
`scripts/wiki_citation_seed.py` (I6/I7 campaigns). Commit these artifacts
after a real `--apply` run so the history of scheduled-groomer activity is
auditable, exactly like the existing campaign journals in `docs/campaigns/`.

## Telemetry — how `get_grooming_health` sees a groomer run

No separate telemetry write is needed. `get_grooming_health`'s per-kind
`last_run_at` is computed from `PgStatsMixin.get_grooming_ages`
(`MAX(wiki.pages.tended)` for wiki; a `distill-of:` tag-prefix scan for
distillation). Both signals are driven by the SAME governed write paths
this script's children use:

- Wiki leg writes go through `write_governed_page`, which updates
  `wiki.pages.tended` on every successful write (G-1) — so a wiki-leg run
  that fills at least one gap immediately un-stales the `wiki` kind on the
  next `get_grooming_health` call.
- Distillation leg writes happen when the `claude -p` child calls
  `remember` with the dossier's marker tag (`distill-of:<hash>`) as
  `build_distill_prompt` instructs — so a successful distillation write
  immediately un-stales the `distillation` kind the same way.

If a distillation child skips a dossier (the prompt explicitly permits
this — "skip this dossier if the sources don't justify a lesson") or
writes without the marker tag (a known, documented trust-boundary gap —
`curate_distill.py` "cannot force the LLM to include the marker tag"), the
kind's age does not advance even though a `claude -p` call was spent. This
is intentional: staleness measures *actual grooming output landing in the
DB*, not *attempts* — `attempted`/`failed`/`skipped-*` counts in the
journal are the attempt-level signal; `get_grooming_health`'s age is the
outcome-level signal. Comparing the two after a run is the recommended way
to notice a low acceptance rate (design doc's own self-flagged risk #3).

## Installing the launchd job (macOS — a user action, not automated)

`scripts/com.cortex.scheduled-groomer.plist` is a **template**, not
installed by this repo. To install:

1. Copy it: `cp scripts/com.cortex.scheduled-groomer.plist
   ~/Library/LaunchAgents/`
2. Edit the copy: replace `/path/to/Cortex` with your actual repo path,
   `REPLACE_ME` with your macOS username (for the log paths and `HOME`),
   and confirm the `PATH` entry covers wherever `uv` and `claude` are
   installed on your machine.
3. Create the log directory: `mkdir -p ~/Library/Logs/cortex-groomer`
4. Load it: `launchctl load ~/Library/LaunchAgents/com.cortex.scheduled-groomer.plist`
5. Verify: `launchctl list | grep com.cortex.scheduled-groomer`

To uninstall: `launchctl unload
~/Library/LaunchAgents/com.cortex.scheduled-groomer.plist && rm
~/Library/LaunchAgents/com.cortex.scheduled-groomer.plist`.

Non-macOS: use `cron` with the equivalent schedule (`0 3 * * 0`) and the
same `--apply` command line; the script itself has no macOS-specific
dependency (the active-session guard's `_pid_alive` degrades to `False`
on unsupported platforms per `session_registry.py`'s own documented
platform-note, never a false attribution).

## Cadence rationale (recap)

Weekly, Sunday 03:00 local time. `GROOMING_STALENESS_THRESHOLD_DAYS = 6.0`
(sourced from measured session cadence, `core/grooming_health.py`). A
7-day cron period means the worst-case delay between a leg going stale and
this script draining it is `6 + 7 = 13` days — an order of magnitude
better than the 76-day silence the design doc measured before any of G-1
through G-4 existed, while not running so often that most weeks would find
nothing due (a fresh leg with backlog is deliberately left to its natural
pace — see `legs_due`'s docstring).
