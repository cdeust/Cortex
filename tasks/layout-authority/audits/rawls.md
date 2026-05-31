# Layout Authority — Rawlsian Fairness Audit

**Method:** veil-of-ignorance scheduling. Behind the veil you do not know which
subscriber you will be. Design drop / shed / queue rules acceptable from every
position. Source: Rawls, *A Theory of Justice* (1971), §3, §13, §39; *Justice as
Fairness: A Restatement* (2001), §13–§19.

Subject under audit: `mcp_server/server/layout_authority_scheduler.py`
(Hamilton 1969 priority-displaced scheduler) and the protocol's drop semantics.

## 1. Stakeholder map (positions behind the veil)

| Position | What they care about | Vulnerability under current rules |
|---|---|---|
| S1. Fast desktop, all-domains | Full graph, edges, symbols | Almost none — gets everything |
| S2. Slow phone, all-domains | Coherent skeleton, low bandwidth | Edges (P5) and symbols (P4) shed first — still readable |
| S3. Freshly-connected (cold start) | One coherent snapshot now | **Loses P4/P5 events that fired before subscription** |
| S4. Long-lived viewer, single-domain filter | Their domain's symbols + edges | **Their P4/P5 are dropped to serve viewers who care about other domains' P0/P1** |
| S5. Background tab (paused render) | Catch up on resume | Subscriber queue overflows; lossy reconnect required |
| S6. All-domains live (dashboard) | Topology updates | Well served — P0–P3 land |
| S7. Edge-only consumer (impact graph) | Edges (P5) | **Worst-off under current rules** — P5 dropped before any node |

## 2. Veil-of-ignorance test on current rules

The scheduler's claim is global: "drop edges before nodes, symbols before files,
files before tool_hubs, tool_hubs before domains." Adopt each position:

| Decision | From S1 | From S4 (single-domain) | From S7 (edge-only) | Verdict |
|---|---|---|---|---|
| Drop P5 edges first | OK | **No** — edges *are* their domain | **No** — that's their entire signal | **Fails** |
| Drop P4 symbols before P2 files | OK | **No** if their domain is symbol-heavy (e.g. one file = 10k symbols → they see one dot) | OK | **Fails for S4** |
| Single global queue cap per priority | OK | **No** — a burst in *another* domain consumes the cap and shadow-drops their work | OK | **Fails for S4** |
| Coalesce P6 by `domain_id` | OK | OK | OK | Passes |
| Strict priority preemption | OK | **No** — their P4 starves indefinitely under sustained P0–P3 load on other domains | **No** | **Fails under sustained load** |

Three of five rules fail the veil from at least one position. The scheduler is
**fair only for the all-domains, full-fidelity desktop subscriber** — i.e. it
optimises for the position that needs no help.

## 3. Difference-principle evaluation

Rule: an inequality is permissible **only if the worst-off position is better
off with it than without it** (Rawls 1971 §13).

| Inequality | Worst-off | Better off than equal-treatment alternative? | Justified? |
|---|---|---|---|
| Domains > tool_hubs > files | S4, S7 | **Yes** — without anchors nobody can place anything; even S7 needs domain coordinates to draw an edge | Yes |
| Files > symbols | S4 (symbol-dense domain) | **No** — equal allocation per domain would give them symbols too | **No** |
| Nodes > edges | S7 | **No** — edge-only consumer is the worst-off and the inequality is built specifically *against* them | **No** |
| Global cap per priority (no per-subscriber accounting) | S4, S5 | **No** — per-domain caps would isolate noisy neighbours from their domain | **No** |

The first inequality (level hierarchy) is justified — without anchors, every
position is worse off. The second and third are **not** justified by the
difference principle: they make the worst-off worse to make the median better.

## 4. Priority-of-liberty check

Rawls' first principle is lexically prior: basic liberties cannot be traded for
efficiency (Rawls 1971 §39; 2001 §13). For a viz scheduler, the analogue
"basic liberties" are:

| Liberty | Currently honoured? |
|---|---|
| L1. **Coherence** — anything shown is structurally valid (no orphan symbols, no edge to missing endpoint) | **Partially** — P4/P5 dropped without their P2/P3 endpoints causes orphan edges and ghost symbols at the renderer |
| L2. **Notice** — subscriber knows when their data was shed | **No** — `is_overloaded()` is producer-facing only; subscribers cannot tell drops from "nothing happened" |
| L3. **Eventual completion** — every accepted node eventually reaches every live subscriber | **No** — subscriber queue overflow is silent; S5 (background tab) loses events forever on resume |
| L4. **Non-discrimination by filter** — a single-domain filter must not be served worse than no-filter | **No** — current global caps mean a noisy domain crowds out a quiet one's events |

L1, L2, L3, L4 are violated for efficiency (memory ceiling, simplicity).
**Lexical priority forbids these trades.** The 8 MB working-set ceiling is
real (cost-model.md), but the trades it forces should land on efficiency
metrics, not on coherence and notice.

## 5. Reflective equilibrium — proposed revisions

Iterate principles ↔ cases until both hold. Concrete revisions, ordered by
the rule they restore:

**R1. Per-domain accounting inside each priority (restores §3 fairness for S4).**
Replace `deque per priority` with `deque per (priority, domain_id)`. Cap per
*pair*, not globally. A symbol burst in domain D consumes only D's P4 cap;
S4 watching domain D' is unaffected. Memory: 11 domains × 7 priorities × small
cap ≈ same order as today; reshape, not grow.

**R2. Edge-aware shedding for edge-subscribers (restores §3 for S7).**
`priority_for_edge()` returns 5 unconditionally. Make it `5` for non-edge
subscribers and `2` (file-tier) when the edge is the *only* signal a
subscriber asked for. The scheduler must know subscriber filters; today it
does not — protocol gap.

**R3. Coherence guard before drop (restores L1).**
Before dropping a P4 symbol whose parent P2 file has already been emitted,
do not drop — apply backpressure to the *producer* of new P4s instead.
Hamilton's BAILOUT shed *jobs*, not state mid-job; same rule here.

**R4. Drop-notification frame (restores L2).**
When `submit` returns False, emit a `{"type":"drop","priority":p,"domain":d}`
event to *all* subscribers whose filter matches. Three bytes of honesty beats
silent loss.

**R5. Subscriber-side replay window (restores L3).**
Each subscriber gets a bounded ring of "events since cursor". On reconnect
(S5) they request `since=cursor`; the authority replays from the ring or
returns `RESYNC` (full snapshot) if the cursor fell off. Same pattern as
Kafka consumer offsets — the position's worst-off (background tab) is
materially better off.

**R6. Lottery for P4 under sustained load (restores starvation-freedom).**
Strict priority guarantees P4 starvation under sustained P0–P3 traffic.
Replace with **weighted fair queueing** (Demers, Keshav, Shenker 1989):
P0 weight 16, P1 weight 8, P2 weight 4, P3 weight 2, P4 weight 1, P5 weight
1, P6 weight 1. Each tick the dispatcher pops in proportion to weights;
P0 still dominates 16:1 but P4 cannot starve forever. The lexical rule
becomes a *steep* preference rather than an *absolute* one — defensible from
S4's position because S4 will eventually see their symbols.

## 6. Process-fairness audit

| Check | Status |
|---|---|
| Transparency — drop policy is documented | Yes (module docstring) |
| Inclusion — subscribers have voice in policy | **No** — purely producer-defined |
| Accountability — drops are observable to affected party | **No** — `stats()` returns server-side aggregates only |
| Appeal — affected subscriber can request resync | **No** — no RESYNC verb exists |

Process is fair to operators, opaque to subscribers. R4 + R5 close the gap.

## 7. Capability correction (Sen 2006)

Equal distribution of "events" does not equal equal capability to render. S2
(slow phone) converts events→pixels at lower rate than S1. After R1–R6, add:

- **Per-subscriber rate negotiation.** Subscriber declares
  `max_events_per_second`; authority pre-aggregates (e.g. coalesces 100 P4
  symbol-adds into one batch frame) before sending. Same data, lower
  conversion cost. This is capability equalisation, not data inequality.

## 8. Verdict

Current Hamilton scheduler is **fair only for the median-rich subscriber**
(S1, S6). It fails the veil from S4 (single-domain), S5 (background tab),
S7 (edge-only) and partially from S3 (cold start). The level hierarchy
(P0 > P1 > P2) survives the difference-principle test; the symbol/edge
relegation and the global (non-per-domain) caps do not.

**Worst-off subscriber today:** S7 (edge-only consumer). Their entire signal
class is the first thing dropped, with no notice and no replay.

**Minimum revisions to pass the veil:** R1 (per-domain caps), R3 (coherence
guard), R4 (drop notification), R5 (replay window). R2 and R6 are
strengthenings; R6 in particular replaces strict priority with weighted
fair queueing so P4 cannot starve.

## 9. Hand-offs

- Per-domain queue *institutional* design (commons governance of shared
  caps): **Ostrom**.
- The irreducible trade-off (someone *must* be shed at 10⁹ nodes / 8 MB —
  name it instead of hiding it): **Le Guin**.
- Debias the operator's "drop edges first, they're just lines" intuition:
  **Kahneman**.
- Implementation of R1–R6 with conventional-commit discipline: **engineer**.

## 10. Compliance with coding-standards.md

Rules 1, 2, 7, 8 (always-on) flagged: R3 (coherence guard) is a §6 root-cause
fix, not a band-aid; R4 (drop notification) restores §7.3 local reasoning by
making "what just happened" visible at the call site; R6 (WFQ) cites Demers
et al. 1989 per §8 source discipline. No invented constants in the proposal —
weights are illustrative and must be measured before commit (§8 rule 4).
