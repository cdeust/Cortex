# Memory Scope Coverage Map

**Companion to:** `memory/scope-registry.json` v2 and `memory/ADR-001-scope-coverage.md`.
**Purpose:** authoritative agent-slug → scope mapping. Refactorer uses this to set `memory_scope:` frontmatter on every agent.
**Last updated:** 2026-04-24

## Conventions

- **Agent slug** = the agent's filename without `.md` (e.g. `agents/engineer.md` → slug `engineer`).
- **Role** = `owner` (write+read) or `reader` (read-only) for that scope.
- **Subpath convention** = where within the scope the agent SHOULD write its files. For team agents this is the scope root (`/memories/<scope>/`). For genius agents this is `/memories/genius/<slug>/` — the convention is mandatory but enforced by description text, not ACL (see ADR-001).

## Systemic scopes (no agent owns these by slug)

| Scope | Owners | Readers | Notes |
|---|---|---|---|
| `global` | `_user`, `_curator` | `*` | Cross-project ground truth. Curator-only writes. |
| `lessons` | `_user`, `_curator` | `*` | Rules from corrections. `orchestrator` writes via `_curator` role. |
| `quarantine` | `*` | `_user`, `_curator` | Untrusted-source writes. Triage-only reads. |
| `session` | `*` | `*` | Ephemeral scratch. TTL 1 day. |
| `project` | `*` | `*` | Per-project durable context. TTL 90 days. |

## Team agents — per-agent scopes (17 entries)

Every team agent owns exactly one scope keyed by its slug. Subpath: `/memories/<slug>/`.

| Agent slug | `memory_scope` | Owner of | Reader of (besides own) |
|---|---|---|---|
| `architect` | `architect` | `architect` | all `*`-readable scopes |
| `code-reviewer` | `code-reviewer` | `code-reviewer` | all `*`-readable scopes |
| `data-scientist` | `data-scientist` | `data-scientist` | all `*`-readable scopes |
| `dba` | `dba` | `dba` | all `*`-readable scopes |
| `devops-engineer` | `devops-engineer` | `devops-engineer` | all `*`-readable scopes |
| `engineer` | `engineer` | `engineer` | all `*`-readable scopes |
| `frontend-engineer` | `frontend-engineer` | `frontend-engineer` | all `*`-readable scopes |
| `latex-engineer` | `latex-engineer` | `latex-engineer` | all `*`-readable scopes |
| `mlops` | `mlops` | `mlops` | all `*`-readable scopes |
| `orchestrator` | `orchestrator` | `orchestrator` + curator role on `global`, `lessons` | all `*`-readable scopes + curator-only readers |
| `paper-writer` | `paper-writer` | `paper-writer` | all `*`-readable scopes |
| `professor` | `professor` | `professor` | all `*`-readable scopes |
| `refactorer` | `refactorer` | `refactorer` | all `*`-readable scopes |
| `reviewer-academic` | `reviewer-academic` | `reviewer-academic` | all `*`-readable scopes |
| `security-auditor` | `security-auditor` | `security-auditor` | all `*`-readable scopes |
| `test-engineer` | `test-engineer` | `test-engineer` | all `*`-readable scopes |
| `ux-designer` | `ux-designer` | `ux-designer` | all `*`-readable scopes |

## Team agents — shared `research` scope (2 entries)

Co-authored by design (research pipeline). Subpath: `/memories/research/`.

| Agent slug | `memory_scope` | Owner of | Notes |
|---|---|---|---|
| `experiment-runner` | `research` | `research` | shared with research-scientist |
| `research-scientist` | `research` | `research` | shared with experiment-runner |

## Genius agents — shared `genius` scope (97 entries)

All genius agents share scope `genius`. Per-agent isolation is by **mandatory subpath convention**: `/memories/genius/<slug>/`. Cross-genius reads are permitted (cross-pollination is the design intent).

`memory_scope: genius` on every entry below. Owner of `genius`. Reader of all `*`-readable scopes. Subpath: `/memories/genius/<slug>/`.

| # | Slug | # | Slug | # | Slug | # | Slug |
|---|---|---|---|---|---|---|---|
| 1 | alexander | 26 | erlang | 51 | laplace | 76 | rawls |
| 2 | alkhwarizmi | 27 | euler | 52 | lavoisier | 77 | rejewski |
| 3 | altshuller | 28 | feinstein | 53 | leguin | 78 | rogerfisher |
| 4 | archimedes | 29 | fermi | 54 | lem | 79 | rogers |
| 5 | arendt | 30 | feynman | 55 | liskov | 80 | schelling |
| 6 | aristotle | 31 | fisher | 56 | mandelbrot | 81 | schon |
| 7 | bateson | 32 | fleming | 57 | margulis | 82 | semmelweis |
| 8 | beer | 33 | foucault | 58 | maxwell | 83 | shannon |
| 9 | borges | 34 | gadamer | 59 | mcclintock | 84 | simon |
| 10 | boyd | 35 | galileo | 60 | meadows | 85 | snow |
| 11 | braudel | 36 | geertz | 61 | mendeleev | 86 | strauss |
| 12 | bruner | 37 | ginzburg | 62 | midgley | 87 | taleb |
| 13 | carnot | 38 | godel | 63 | mill | 88 | thompson |
| 14 | champollion | 39 | hamilton | 64 | nagarjuna | 89 | toulmin |
| 15 | coase | 40 | hart | 65 | noether | 90 | turing |
| 16 | cochrane | 41 | hopper | 66 | ostrom | 91 | varela |
| 17 | curie | 42 | ibnalhaytham | 67 | panini | 92 | ventris |
| 18 | darwin | 43 | ibnkhaldun | 68 | pearl | 93 | vonneumann |
| 19 | deming | 44 | jobs | 69 | peirce | 94 | vygotsky |
| 20 | dijkstra | 45 | kahneman | 70 | poincare | 95 | wittgenstein |
| 21 | eco | 46 | kauffman | 71 | polya | 96 | wu |
| 22 | einstein | 47 | kay | 72 | popper | 97 | zhuangzi |
| 23 | ekman | 48 | kekule | 73 | propp |  |  |
| 24 | engelbart | 49 | knuth | 74 | ramanujan |  |  |
| 25 | erdos | 50 | lamport | 75 | ranganathan |  |  |

> **NOTE:** `agents/genius/INDEX.md` is not an agent — it is the directory index. It does not get a `memory_scope` and does not count toward the 97.

## Coverage summary

| Category | Count | Coverage |
|---|---|---|
| Team agents (excl. genius) | 19 | 19 / 19 = 100% |
| Genius agents | 97 | 97 / 97 = 100% |
| **Total agents** | **116** | **100%** |
| Distinct registry scopes | 24 | (5 systemic + 17 team + 1 research + 1 genius) |

## Refactorer checklist

For every agent file under `agents/`:

1. Read the agent's filename slug.
2. Look up the slug in this document.
3. Set frontmatter `memory_scope: <scope>` to the value in the table.
4. For genius agents, additionally document the subpath convention in the agent's `<memory>` section: "Write under `/memories/genius/<slug>/`."
5. Commit per-agent (one frontmatter change per commit) so blast radius stays scoped.

## Adding a new agent (post-rollout)

1. Decide: team agent or genius?
2. **Team agent:** add a new scope entry to `scope-registry.json` keyed by the slug, owners `[<slug>, "_user"]`, readers `["*"]`, ttl_days 30, max_file_kb 100. Add a row to the team table above. Set agent frontmatter `memory_scope: <slug>`.
3. **Genius agent:** no registry change needed. Add a row to the genius table above. Set agent frontmatter `memory_scope: genius`. Document subpath in agent's `<memory>` section.
4. Open a PR; require curator review (orchestrator or `_user`).

## Verification

```bash
python3 -c 'import json; d=json.load(open("memory/scope-registry.json")); print("scopes=", len(d["scopes"]), "strict=", d["strict_unknown_scope"], "curators=", d["curator_agents"])'
```

Expected: `scopes= 24 strict= True curators= ['_user', 'orchestrator']`
