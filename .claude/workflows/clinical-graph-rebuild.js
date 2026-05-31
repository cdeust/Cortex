// Clinical-hospital graph viz rebuild — full implementation workflow.
//
// Purpose
// -------
// Build a fresh visualization UI at ui/clinical/ that follows the
// "clinical hospital" navigation model:
//   1. Open at BIG PICTURE — domains + structural hubs only.
//   2. ZOOM IN one cut at a time (scroll/pinch) to load the next phase
//      (L0 → L1 → L2 → L3 → L4 → L5 → L6).
//   3. CLICK A NODE → opens that node's chain-of-call / chain-of-action
//      as a SEPARATE graph view, never polluting the main view.
//   4. Zero JS errors permitted (verify phase enforces).
//
// Foundation
// ----------
// * Sigma.js + graphology (WebGL renderer, scales to 100 k+ nodes).
// * Vendored offline at ui/clinical/vendor/.
// * Apache Arrow JS for /api/quadtree position decode.
//
// Server contract this depends on
// -------------------------------
// All endpoints already on origin/main (see PR #50):
//   GET /api/graph/progress              phase state + readiness
//   GET /api/graph/phase?name=L0..L6...  per-phase {nodes, edges}
//   GET /api/graph                       cumulative JSON cache
//   GET /api/graph.bin                   CXGB binary snapshot
//   GET /api/quadtree                    Apache Arrow IPC (id, x, y, kind)
//   GET /api/graph/events                SSE batches during build
//
// Where to run
// ------------
// From the repo root, on a machine with the dev server reachable:
//   Workflow({ scriptPath: '.claude/workflows/clinical-graph-rebuild.js' })
//
// The branch viz/ui-clinical-rebuild is pre-created and pushed; this
// workflow's Commit phase will commit + push + open a PR against main.

export const meta = {
  name: 'clinical-graph-rebuild',
  description: 'Build the clinical-hospital graph viz at ui/clinical/ — Sigma.js + graphology, big-picture→zoom-in→sub-graph, zero JS errors',
  phases: [
    { title: 'Spec',     detail: '3 parallel design agents — navigation model, sub-graph drill-down, streaming wire-up' },
    { title: 'Scaffold', detail: 'create ui/clinical/, vendor sigma.js + graphology, write boot HTML + module skeleton' },
    { title: 'Big-pic',  detail: 'implement the landing big-picture view (domains + structural backbone) from /api/graph/phase' },
    { title: 'Zoom',     detail: 'progressive zoom-in: scroll/pinch deepens the visible phase (L0→L1→L2→L3)' },
    { title: 'Sub-graph', detail: 'node click opens chain-of-call/action as a SEPARATE graph view (modal/side panel)' },
    { title: 'Live',     detail: 'wire /api/graph/events SSE for incremental updates after initial paint' },
    { title: 'Verify',   detail: '4 parallel adversarial verifiers — JS syntax, console.error hunt, accessibility, smoke test' },
    { title: 'Commit',   detail: 'final review pass + git commit + push + open PR' },
  ],
}

const SPEC_SCHEMA = {
  type: 'object',
  properties: {
    title: { type: 'string' },
    decisions: {
      type: 'array',
      items: { type: 'object', properties: {
        decision: { type: 'string' },
        rationale: { type: 'string' },
      }, required: ['decision', 'rationale'] }
    },
    api_endpoints_used: { type: 'array', items: { type: 'string' } },
    pseudocode: { type: 'string' },
  },
  required: ['title', 'decisions', 'api_endpoints_used', 'pseudocode'],
  additionalProperties: false,
}

const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    files_written: { type: 'array', items: { type: 'string' } },
    files_modified: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
  required: ['files_written', 'files_modified', 'summary'],
  additionalProperties: false,
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    check: { type: 'string' },
    passed: { type: 'boolean' },
    findings: {
      type: 'array',
      items: { type: 'object', properties: {
        severity: { type: 'string', enum: ['blocker', 'warning', 'info'] },
        file: { type: 'string' },
        line: { type: 'number' },
        message: { type: 'string' },
      }, required: ['severity', 'message'] }
    },
  },
  required: ['check', 'passed', 'findings'],
  additionalProperties: false,
}

// ── Shared context every agent gets ──
const CTX = `
PROJECT: Cortex — neural graph visualization rebuild.
BRANCH:  viz/ui-clinical-rebuild (already created, ready for commits)
TARGET:  ui/clinical/   ← NEW directory, do not touch ui/unified/* or ui/dashboard/*

DESIGN PRINCIPLE — "Clinical hospital" navigation:
  1. Open at BIG PICTURE — domains + structural hubs only (~50–500 nodes).
     Like seeing the hospital from the entrance: corridors, wings,
     departments. NOT every patient room at once.
  2. ZOOM IN (scroll / pinch) progresses one layer deeper.
     L0 domains → L1 setup (skills/hooks/agents/commands) → L2 tools →
     L3 files → L4 discussions → L5 memories → L6 symbols.
     User-controlled. Each zoom level loads the next /api/graph/phase
     batch and fades it in around the existing nodes.
  3. CLICK A NODE → opens that node's CHAIN-OF-CALL / CHAIN-OF-ACTION
     as a SEPARATE graph view (modal, side panel, or routed page).
     Does NOT pollute the main big-picture view.
  4. ZERO JavaScript errors permitted — every console.error or
     uncaught throw blocks the verify phase.

RENDERER: Sigma.js + graphology (WebGL).
  Vendored offline at ui/clinical/vendor/sigma.min.js + graphology.umd.min.js
  (the scaffold step downloads them).

SERVER CONTRACT (already on the branch, no changes needed):
  GET /api/graph/progress              → {phase, pct, phases{key→bool}, full_ready, message, elapsed, …}
  GET /api/graph/phase?name=<key>      → {nodes:[], edges:[], ready:bool, node_total:int, edge_total:int, phase:str, deps:[]}
  GET /api/graph                       → cumulative cached snapshot (JSON)
  GET /api/quadtree                    → Apache Arrow IPC (id, x, y, kind) — returns 503 {reason:"no_layout"} until recompute_layout has run; handle this gracefully
  GET /api/graph/events                → SSE batches (event:batch data:{label,nodes,edges,off,n_total,e_total}; event:done data:{total_nodes,total_edges})
  GET /api/recompute_layout            → triggers DrL layout computation; call once during scaffold setup

IMPORTANT — phase key naming:
  L0..L5 are fixed keys. L6 phases are DYNAMIC: key format is "L6:<project-slug>" (e.g. "L6:cortex").
  NEVER hardcode "L6" as a phase key. Instead enumerate dynamic keys from /api/graph/progress .phases dict.
  Example: Object.keys(progress.phases).filter(k => k.startsWith('L6:')) gives all L6 sub-phases.

IMPORTANT — cold-start sequence:
  Use SSE (/api/graph/events) as the primary data channel. Do NOT use /api/graph.bin
  (CXGB binary decoder is not bundled). Cold-start = fetch L0+L1 via /api/graph/phase,
  then subscribe to SSE for remaining phases.

IMPORTANT — /api/quadtree positions:
  Positions come from DrL layout (not ForceAtlas2). On fresh server start the quadtree
  may return 503 {reason:"no_layout"}. Handle this: fall back to graphology's built-in
  circular layout for initial render, then update positions when quadtree becomes available.

CONSTRAINTS:
  * Do not touch ui/unified/*, ui/dashboard/*, ui/methodology/* — they stay.
  * No console.log spam in shipping code (warn/error/info only on real events).
  * No JS syntax errors (node --check must pass on every file).
  * No console.error or uncaught throw at runtime (verify phase enforces this).
  * Every fetch() has a .catch() that surfaces a user-visible status, not silent fail.
  * One module per concern, no monolithic file > 500 lines.
  * No new MCP-server / Python changes; this rebuild is UI-only.
  * Sigma v3 vendored at ui/clinical/vendor/sigma.min.js (already downloaded).
  * graphology v0.25.4 vendored at ui/clinical/vendor/graphology.umd.min.js (already downloaded).
  * sigma exports window.Sigma; graphology exports window.graphology — use these globals from vendor scripts.
  * Duplicate node guard: track loadedPhases (Set) and pendingPhases (Set) in streaming.js;
    check both before every /api/graph/phase fetch to prevent addNode on existing id (Sigma throws).
  * SSE done event: call source.close() in the 'done' event handler to prevent auto-reconnect loop.
`

phase('Spec')

// 3 spec agents in parallel — each writes ONE markdown spec under
// ui/clinical/docs/. They don't touch JS so parallel is safe.
const specs = await parallel([
  () => agent(`${CTX}

ROLE: Navigation-model designer for the clinical-hospital graph rebuild.

WRITE: ui/clinical/docs/01-navigation-model.md (markdown spec, 80–150 lines).

INCLUDE:
  * The zoom-state state machine (current_depth: 0..6, transitions on
    scroll, pinch, double-click).
  * Which /api/graph/phase calls fire at each depth level.
  * What stays visible vs what fades in vs what fades out as depth changes.
  * Hit-test strategy at each depth (cursor radius, label visibility).
  * Pan/zoom behaviour (free pan; zoom is the depth control).
  * How a returning user lands (default depth 1? remember last?).

RETURN the schema-shaped summary. Files written goes in 'pseudocode'
as a brief outline of the actual code structure the implementer will follow.`,
    { schema: SPEC_SCHEMA, label: 'spec:navigation' }),

  () => agent(`${CTX}

ROLE: Sub-graph drill-down designer.

WRITE: ui/clinical/docs/02-sub-graph-drill-down.md (markdown spec, 80–150 lines).

INCLUDE:
  * How a node-click triggers a sub-graph view (modal? side panel?
    routed page? Justify the choice given the navigation model.)
  * Which server endpoints provide the chain-of-call / chain-of-action
    data for a given node (use /api/graph for cumulative + filter
    client-side, or do we need a new endpoint?).
  * Sub-graph rendering: separate Sigma instance? Reuse main? Justify.
  * Back-navigation from sub-graph to big-picture (and resume depth).
  * Per-kind sub-graph variants (memory shows its causal chain;
    symbol shows defined_in + calls + member_of; file shows tool
    accesses).

If a new server endpoint is genuinely needed, list it under
'open_questions' so the user can decide whether to add it later.`,
    { schema: SPEC_SCHEMA, label: 'spec:sub-graph' }),

  () => agent(`${CTX}

ROLE: Streaming + initial-load wire designer.

WRITE: ui/clinical/docs/03-streaming-load.md (markdown spec, 80–150 lines).

INCLUDE:
  * Cold-start sequence: progress poll → CXGB snapshot if available →
    fall back to /api/graph JSON → engage SSE for tail batches.
  * How to map SSE batch events to per-depth additions without
    overwhelming the renderer (queue + drain pattern; cite a max
    additions per frame).
  * Error/reconnect strategy when SSE drops mid-build.
  * How the renderer handles a position-less node (no entry in
    /api/quadtree yet) — initial spawn at neighbour centroid or domain
    anchor; never NaN.
  * Loading UI: progress bar wired to /api/graph/progress.pct,
    phase-name display.`,
    { schema: SPEC_SCHEMA, label: 'spec:streaming' }),
])

const validSpecs = specs.filter(Boolean)
log(`Specs complete: ${validSpecs.length}/3`)
for (const s of validSpecs) log(`  - ${s.title}`)

phase('Scaffold')

const scaffold = await agent(`${CTX}

ROLE: Scaffold engineer.

CREATE the ui/clinical/ directory with this exact layout:
  ui/clinical/
    index.html               ← boot page with one <div id="graph">,
                                no inline scripts beyond a single
                                <script type="module" src="js/boot.js">.
    css/
      theme.css              ← dark cyber theme (steal palette from
                                ui/unified/css/theme.css but trim to
                                only what we use).
      layout.css             ← grid: header, main canvas, side panel.
    js/
      boot.js                ← module entry; imports modules below.
      state.js               ← reactive state store (currentDepth,
                                selectedNodeId, loadingPhase, …).
      api.js                 ← fetch wrappers for every server endpoint.
                                Every fetch returns a Promise that
                                surfaces errors via state.lastError;
                                no silent .catch(()=>{}).
      renderer.js            ← Sigma + graphology instance creator.
                                Exports { mount, addNodes, addEdges,
                                clear, onNodeClick }.
      navigation.js          ← zoom-state machine from spec 01.
                                Stub for now; populated in phase 'Zoom'.
      subgraph.js            ← sub-graph view from spec 02. Stub now.
      streaming.js           ← SSE subscriber from spec 03. Stub now.
    vendor/                  ← VENDORED libs (download from CDN):
      sigma.min.js           ← https://cdn.jsdelivr.net/npm/sigma@3.0.0/dist/sigma.min.js
      graphology.umd.min.js  ← https://cdn.jsdelivr.net/npm/graphology@0.25.4/dist/graphology.umd.min.js
    docs/                    ← spec files already written by Spec phase.

ALSO:
  * Add a route in mcp_server/server/http_standalone.py (or its
    dispatch table) so /clinical/ serves ui/clinical/index.html and
    /clinical/<path> serves ui/clinical/<path>. If you need to grep
    for the existing static-route logic, do so. Keep the route
    additive — do NOT remove the existing /unified/ route.
  * Each .js file MUST pass 'node --check'. Run that as part of
    your work.

NOTE: vendor libs are ALREADY downloaded at ui/clinical/vendor/sigma.min.js
and ui/clinical/vendor/graphology.umd.min.js — do NOT re-download them.

USE Read on ui/clinical/docs/01-navigation-model.md, 02, 03 (they
exist now from the Spec phase) to extract anything the scaffold needs.

After wiring /clinical/ in http_standalone.py (already done — do NOT re-add it),
trigger layout pre-computation so /api/quadtree has data:
  curl -s http://127.0.0.1:3458/api/recompute_layout || true
(best-effort; ui gracefully falls back to circular layout on 503).

RETURN the IMPL_SCHEMA shape.`,
  { schema: IMPL_SCHEMA, label: 'scaffold', model: 'sonnet' })

log(`Scaffold: ${scaffold ? scaffold.summary : 'FAILED'}`)
if (!scaffold) {
  log('Scaffold failed; aborting workflow.')
  return { aborted: 'scaffold' }
}

phase('Big-pic')

const bigpic = await agent(`${CTX}

ROLE: Big-picture landing-view implementer.

GOAL: when ui/clinical/index.html loads, the browser should:
  1. Show a "loading…" status.
  2. Fetch /api/graph/progress; show the phase + pct on screen.
  3. Fetch /api/graph/phase?name=L0 (domains) and /api/graph/phase?name=L1
     (setup) — these together form the structural backbone.
  4. Fetch /api/quadtree (Apache Arrow IPC of positions) — decode it,
     resolve every node's (x,y) from the payload.
  5. Mount the Sigma renderer with those nodes (domains + setup) at
     their precomputed positions. Draw edges between them from the
     phase payloads.
  6. Loading status fades to "ready".

IMPLEMENT in:
  ui/clinical/js/api.js   — fetch helpers (getProgress, getPhase,
                            getQuadtree, decoded as a Map<id, {x,y,kind}>)
  ui/clinical/js/renderer.js — Sigma mount with graphology graph instance
  ui/clinical/js/boot.js     — wires the cold-start sequence

CONSTRAINTS:
  * NO sigma.js force layout — positions come from /api/quadtree only.
    Sigma's default layout is fine for nodes without positions; for
    nodes with positions, set them and disable physics.
  * Vendor Apache Arrow JS too if needed (ui/clinical/vendor/apache-arrow.min.js).
  * Catch every fetch error and surface it in the on-screen status.
  * Every file 'node --check' clean.

Read ui/clinical/docs/01-navigation-model.md first for the depth=0
spec. Read renderer.js as scaffolded; replace stubs with real code.

RETURN IMPL_SCHEMA.`,
  { schema: IMPL_SCHEMA, label: 'big-picture', model: 'sonnet' })

log(`Big-pic: ${bigpic ? bigpic.summary : 'FAILED'}`)
if (!bigpic) {
  log('Big-picture failed; aborting workflow.')
  return { aborted: 'big-picture' }
}

phase('Zoom')

const zoom = await agent(`${CTX}

ROLE: Progressive-zoom implementer.

GOAL: scroll/pinch deepens the visible phase. Specifically:
  * Default depth = 1 (after big-picture loaded L0 + L1, depth=1).
  * Scroll IN: depth++ (max 6). Fetches the next phase and adds its
    nodes via Sigma's addNode + addEdge. New nodes fade in at their
    /api/quadtree position (or, if not yet computed, at the centroid
    of their existing-rendered neighbours).
  * Scroll OUT: depth--. Hides (not removes) the deeper-phase nodes.
    Toggling depth back IN re-shows them without re-fetching.
  * Depth indicator shown on-screen ("L3 files · 14 022 nodes").

IMPLEMENT in:
  ui/clinical/js/navigation.js — the zoom-state machine
  ui/clinical/js/renderer.js   — addNodes(slice) + addEdges + hide/show
                                  per depth band
  ui/clinical/js/boot.js       — wires the scroll event to navigation

CONSTRAINTS:
  * Use sigma's camera API for actual visual zoom; the SEMANTIC
    depth (which phases are loaded) is a separate variable.
  * No re-fetch of an already-loaded phase.
  * Loading a phase is async — show a spinner near the depth indicator.

RETURN IMPL_SCHEMA.`,
  { schema: IMPL_SCHEMA, label: 'zoom', model: 'sonnet' })

log(`Zoom: ${zoom ? zoom.summary : 'FAILED'}`)
if (!zoom) {
  log('Zoom failed; aborting workflow.')
  return { aborted: 'zoom' }
}

phase('Sub-graph')

const subgraph = await agent(`${CTX}

ROLE: Sub-graph drill-down implementer.

GOAL: clicking a node opens its chain-of-call / chain-of-action as a
SEPARATE graph view. The main view stays put behind it.

IMPLEMENT in:
  ui/clinical/js/subgraph.js
  ui/clinical/index.html — add a <dialog id="subgraph"> with its own
                            <div id="subgraph-canvas"> for the second
                            Sigma instance.
  ui/clinical/css/layout.css — modal styling

PER spec 02:
  * Render in a SEPARATE Sigma instance (do not mutate the main one).
  * For a symbol node: show its defined_in file, callees, callers,
    siblings (member_of-same-class).
  * For a memory node: show entities-it-mentions + neighbour-memories
    via co-access.
  * For a file node: show symbols-it-defines + tools-that-touched-it.
  * "Close" button + Esc key dismiss the modal AND return camera to
    its previous position on the main graph.

CONSTRAINTS:
  * The sub-graph fetches are best-effort filters over the cumulative
    /api/graph JSON cached on the client at load time. Do NOT add a
    new server endpoint.

RETURN IMPL_SCHEMA. List any per-kind that you stubbed out as
"open_questions".`,
  { schema: IMPL_SCHEMA, label: 'sub-graph', model: 'sonnet' })

log(`Sub-graph: ${subgraph ? subgraph.summary : 'FAILED'}`)
if (!subgraph) {
  log('Sub-graph failed; aborting workflow.')
  return { aborted: 'sub-graph' }
}

phase('Live')

const live = await agent(`${CTX}

ROLE: Live-streaming implementer.

GOAL: After the initial big-picture mount, the SSE stream at
/api/graph/events keeps delivering batches as the server's build
progresses. Each batch's nodes/edges should fade in at the current
depth IF they belong to a phase that's currently visible.

IMPLEMENT in:
  ui/clinical/js/streaming.js
  ui/clinical/js/boot.js  — attach the SSE subscriber after big-picture
                            mount succeeds.

PER spec 03:
  * Use EventSource on /api/graph/events.
  * Parse each batch event ({label, nodes, edges, off, n_total, e_total}).
  * Enqueue into a pendingDelta. A rAF-driven drain pops max 200 nodes
    + 400 edges per frame and calls renderer.addNodes/addEdges.
  * If the batch's label corresponds to a depth NOT currently visible,
    still buffer the data internally so zoom-in finds it; just don't
    render yet.
  * On reconnect, resume from the last-received id (use
    EventSource's built-in Last-Event-ID behaviour).

RETURN IMPL_SCHEMA.`,
  { schema: IMPL_SCHEMA, label: 'streaming', model: 'sonnet' })

log(`Live: ${live ? live.summary : 'FAILED'}`)
if (!live) {
  log('Live streaming failed; aborting workflow.')
  return { aborted: 'live' }
}

phase('Verify')

// 4 parallel adversarial verifiers
const verifications = await parallel([
  () => agent(`${CTX}

ROLE: JS syntax + import verifier.

CHECK every .js file under ui/clinical/js/ with 'node --check'.
ALSO ensure every relative import path resolves (the file at the
target path exists).

Use Bash for 'node --check' and Read for paths.

RETURN VERIFY_SCHEMA. 'check' = 'js-syntax+imports'. Any failure is
a blocker.`,
    { schema: VERIFY_SCHEMA, label: 'verify:syntax' }),

  () => agent(`${CTX}

ROLE: console.error + uncaught throw hunter.

REVIEW every .js file under ui/clinical/js/ for:
  * console.error / console.warn calls — are they in error paths
    only, or accidentally on the hot path?
  * throw new Error(...) — are they caught upstream?
  * Promise chains without .catch() — silent rejection.
  * Unhandled event-handler exceptions (addEventListener bodies
    should try/catch).
  * Any access of obj.x.y where x might be undefined (defensive
    null checks).

Use Grep + Read.

RETURN VERIFY_SCHEMA. 'check' = 'console-errors'. Each suspect is a
warning unless it's a hot-path throw (blocker).`,
    { schema: VERIFY_SCHEMA, label: 'verify:errors' }),

  () => agent(`${CTX}

ROLE: Accessibility + UX sanity verifier.

REVIEW ui/clinical/index.html + index.html-loaded CSS for:
  * Keyboard navigation: Tab order sensible? Esc dismisses modal?
  * Color contrast at AA level (dark theme; 4.5:1 for body text).
  * aria-* attributes on interactive controls.
  * No empty <button>s without label or aria-label.
  * Status messages announced via role="status" or aria-live.

Use Read.

RETURN VERIFY_SCHEMA. 'check' = 'accessibility'. Findings = warnings
unless they break Esc / keyboard navigation (blocker).`,
    { schema: VERIFY_SCHEMA, label: 'verify:a11y' }),

  () => agent(`${CTX}

ROLE: End-to-end smoke test harness.

PRODUCE a test plan that a developer can run by hand (we don't have
playwright/puppeteer in this repo). Write it to:
  ui/clinical/docs/04-smoke-test.md

Cover:
  * Cold-start: open /clinical/, expect big-picture in <3 s.
  * Zoom-in: scroll in, expect next phase loaded.
  * Click a domain node: expect domain detail sub-graph.
  * Click a memory node: expect chain-of-action sub-graph.
  * Esc closes sub-graph; main view restored.
  * SSE: open a fresh build, expect nodes streaming in.
  * Window resize: expect canvas reflow, no console errors.

RETURN VERIFY_SCHEMA. 'check' = 'smoke-plan'. passed=true once the
plan exists; findings list each scenario as info-level.`,
    { schema: VERIFY_SCHEMA, label: 'verify:smoke' }),
])

const verifyResults = verifications.filter(Boolean)
const blockers = verifyResults.flatMap(v =>
  (v.findings || []).filter(f => f.severity === 'blocker')
)
log(`Verify: ${verifyResults.length}/4 checks ran, ${blockers.length} blockers`)
for (const b of blockers) log(`  BLOCKER ${b.file || ''} ${b.line || ''}: ${b.message}`)

if (blockers.length > 0) {
  log('Blockers present — refusing to commit. Workflow ends here.')
  return { aborted: 'verify-blockers', blockers, verifyResults }
}

phase('Commit')

const finalCommit = await agent(`${CTX}

ROLE: Final commit + push agent.

DO:
  1. Run: git status   (sanity check what's about to be committed)
  2. Run: git add ui/clinical/   (and the server route change to
     http_standalone.py if scaffold made one — git status will show)
  3. git commit with a thorough message describing what landed.
  4. git push -u origin viz/ui-clinical-rebuild
  5. Open a PR via 'gh pr create' targeting viz/server-streaming-pipeline
     (NOT main — main doesn't have the server endpoints yet; they land via PR #50).
     PR body: clinical-hospital navigation, big-picture default,
     zoom-in deepens phase, click opens separate sub-graph, all
     glued to the server contract from PR #50.

RETURN IMPL_SCHEMA. 'summary' = final state + PR URL.`,
  { schema: IMPL_SCHEMA, label: 'commit', model: 'sonnet' })

return {
  specs: validSpecs,
  scaffold,
  bigpic,
  zoom,
  subgraph,
  live,
  verifyResults,
  blockers,
  finalCommit,
}
