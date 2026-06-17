# Pyright Remediation Plan

**Status:** Draft — 2026-06-17
**Author:** engineer agent
**Input:** taxonomy of 566 errors / 5 warnings from measured pyright run

---

## 1. Reality Check — Env-Import Noise vs Real Backlog

Of the 566 reported errors, **129 are env-import noise** that vanish the moment
third-party packages are installed in the type-check CI job. They are instrument
error, not bugs.

| Category | Count | Source |
|---|---|---|
| `reportMissingImports` | 85 | `fastmcp`, `psycopg`, `tree_sitter`, `pydantic`, `sentence_transformers`, `flashrank`, `torch`, `pgvector`, others |
| `reportMissingModuleSource` (warnings) | 5 | `networkx` ×3, `dateutil` ×2 (stubs-only install) |
| Cascade `reportAttributeAccessIssue` | 19 | `object.nodes`, `object.number_of_nodes` — networkx resolved as `object` |
| Cascade `reportArgumentType` | 18 | downstream of `Unknown` typed returns |
| Cascade `reportReturnType` | 4 | downstream of unresolved types |
| Cascade `reportOperatorIssue` | 3 | `object + str`, `Unknown / float` |
| Cascade `reportGeneralTypeIssues` | 2 | `object` not iterable |
| **Total noise** | **129** | |

**True backlog after env fix: 437 real errors.**

The 437 decompose into three structural root causes that account for ~387 of them.
The remaining ~50 are genuine one-off arity/operator mismatches.

### Root causes (ranked by count)

| # | Root cause | Rules affected | Est. count |
|---|---|---|---|
| RC-1 | `MemoryStore` is a factory (`__new__` returning `PgMemoryStore | SqliteMemoryStore | object`) annotated as a class, not a Protocol. Handlers annotate parameters as `MemoryStore` but receive concrete types that pyright cannot verify against each other. ~30 methods on each concrete store (`insert_rule`, `insert_entity`, `get_checkpoint`, etc.) are called through the `MemoryStore` name which declares none of them. | `reportAttributeAccessIssue` (189), `reportAssignmentType` (26) | **~215** |
| RC-2 | Return-type annotation drift: functions annotated `dict[str, float]` return `dict[str, str \| float]` or richer unions. Concentrated in `core/emergence_metrics.py`, `core/interference.py`, `handlers/codebase_analyze.py`. | `reportReturnType` (43) | **~43** |
| RC-3 | Optional-not-guarded: store-factory helpers return `MemoryStore \| None`; callers assign to `MemoryStore` and dereference immediately without a `None`-guard. Represents real potential `AttributeError` on `None`. | `reportOptionalMemberAccess` (8), `reportCallIssue` (9), `reportReturnType` (14) | **~31** |
| RC-4 | Scattered genuine one-offs: tuple-key arity mismatches, real argument-type disagreements after env noise is stripped. | `reportArgumentType` (~30 real), residual `reportCallIssue` | **~50** |

**Bottom line:** fix the env job, declare one Protocol, widen ~43 return annotations,
add ~10 None-guards. That clears ~387 of 437 errors mechanically. The remaining ~50
require case-by-case triage.

---

## 2. Strategy Decision — How to Make Pyright Blocking Incrementally

**Three options evaluated:**

| Option | Pros | Cons |
|---|---|---|
| (a) Per-layer ratchet | Maps to Clean Architecture; easy to reason about blast radius | Handler layer (290 errors) is far from clean; blocks on the largest, messiest scope first |
| (b) Per-rule ratchet | Targets highest-value rules (real bugs) first; each PR is narrowly scoped | Some rules (`reportAttributeAccessIssue`) span both noise and real errors — requires careful split |
| (c) Baseline grandfather | Blocks only new errors immediately; zero upfront cost | Does not reduce the existing debt; old errors stay unaddressed indefinitely |

**Recommendation: per-rule ratchet (option b).**

Rationale (drawing on the taxonomy):
- The noise-vs-real split is cleanest at the rule level: `reportMissingImports` (85) and
  `reportMissingModuleSource` (5) are almost entirely noise; eliminating them by installing
  deps does not require touching source code at all.
- `reportOptionalMemberAccess` (8) and `reportCallIssue` (9) are almost entirely real bugs;
  enabling them as blocking is high-signal at low count.
- `reportAssignmentType` (26) is entirely RC-1 (Protocol gap) — one structural fix clears the
  whole rule; it becomes a clean zero.
- `reportAttributeAccessIssue` (337) is the last to block because it is the largest and most
  contaminated (noise cascades inflate it); it gates on RC-1 being done.

**Implementation:** pyright supports per-file and project-wide rule severity via
`pyrightconfig.json`. The ratchet is a CI job that runs `pyright --outputjson`,
counts errors per rule, and fails if any tracked rule's count exceeds its committed
baseline. Commit `typecheck-baseline.json` after each phase; the gate compares
current counts against the committed file.

**Guardrails (non-negotiable):**
- No blanket `# type: ignore` suppressions.
- No cast-to-`Any` to silence errors.
- `reportMissingImports` is handled by installing `.[dev,postgresql,codebase]`
  in the CI type-check job, not by suppression.
- `reportMissingModuleSource` for stubs-only packages (`networkx`, `dateutil`) is
  handled by setting `reportMissingModuleSource = "none"` in `pyrightconfig.json`
  scoped to those modules only — with a comment citing why (stubs-only installs with
  no source distribution; type correctness is carried by the stubs).

---

## 3. Phased Batches

### Batch 0 — Environment Resolution (CI + config only, no source changes)

| Field | Value |
|---|---|
| Scope | CI workflow + `pyrightconfig.json` (new file) |
| Estimated errors cleared | 129 |
| Estimated effort | S (half a day) |
| Real bugs likely | No |
| CI change | Add `pip install -e ".[dev,postgresql,codebase]"` to the type-check step; commit `pyrightconfig.json` with stubs-only overrides; commit `typecheck-baseline.json` after re-run |

**Exact actions:**
1. Add type-check CI step: `pip install -e ".[dev,postgresql,codebase]"` before `pyright`.
2. Create `pyrightconfig.json`:
   ```json
   {
     "include": ["mcp_server"],
     "pythonVersion": "3.10",
     "typeCheckingMode": "basic",
     "reportMissingModuleSource": "none",
     "reportMissingImports": "error"
   }
   ```
   Note: `reportMissingImports` stays as `"error"` — after the install it should fire zero
   times. If it fires, the install is incomplete, not the code. The `reportMissingModuleSource`
   override silences stubs-only packages globally (networkx, dateutil wheels ship stubs).
3. Run `pyright --outputjson > typecheck-baseline.json`; commit it.
4. CI gate (pseudo-code):
   ```bash
   pyright --outputjson > current.json
   python scripts/check_pyright_ratchet.py current.json typecheck-baseline.json
   ```
   The ratchet script fails if any rule's count in `current.json` exceeds the baseline.
   At Batch 0, all rules are in `continue-on-error` mode — the ratchet runs but does not
   block the build. Blocking is enabled rule-by-rule in subsequent batches.

**Expected baseline after Batch 0:** ~437 errors across the real rules.

---

### Batch 1 — Optional-Not-Guarded (RC-3) — make blocking immediately

| Field | Value |
|---|---|
| Scope | ~10 handler files around store-factory call sites |
| Estimated errors cleared | 31 |
| Estimated effort | S–M (1–2 days) |
| Real bugs likely | **Yes — real None-deref crashes** |
| CI change | Set `reportOptionalMemberAccess` and `reportCallIssue` to blocking in ratchet |

**Why first after Batch 0:** these 8 + 9 = 17 errors are the highest bug-likelihood
per error in the entire taxonomy. Each `reportOptionalMemberAccess` is a production
`AttributeError` on `None` waiting for the branch where the factory fallback fires.
The count is small, making the PR reviewable. The fix is local to handlers (no
Protocol or return-type changes required).

**Fix pattern:** at every site where `get_shared_store(...)` is assigned to a variable
annotated `MemoryStore`, either:
  - Widen the annotation to `PgMemoryStore | SqliteMemoryStore` (if the concrete type
    matters downstream), or
  - Add an explicit `None`-guard: `if store is None: raise RuntimeError(...)`.

**Note:** `_construct_store` already raises when `allow_fallback` is False; the
`None` returns only surface from `_try_pg` (internal). Making the return type of
`get_shared_store` non-Optional is the correct long-term fix (it either returns a
live store or raises — the `None` case is already an internal implementation detail
that should not leak). Annotate `get_shared_store` → `PgMemoryStore | SqliteMemoryStore`
and propagate. This resolves RC-3 at its source.

**CI after Batch 1:** `reportOptionalMemberAccess` and `reportCallIssue` are both
set to blocking (baseline = 0 for each).

---

### Batch 2 — MemoryStore Protocol Gap (RC-1) — the structural fix

| Field | Value |
|---|---|
| Scope | `mcp_server/infrastructure/memory_store.py` (Protocol definition), 5 `pg_store_*.py` files, ~30 handler files |
| Estimated errors cleared | ~215 |
| Estimated effort | L (3–5 days) |
| Real bugs likely | Yes (callers calling methods that aren't on the type) |
| CI change | Set `reportAssignmentType` to blocking; set `reportAttributeAccessIssue` baseline to ~128 (noise was already removed in Batch 0; real non-Protocol hits cleared) |

**Root cause:** `MemoryStore` is a factory class (uses `__new__` to return
`PgMemoryStore | SqliteMemoryStore | object`). It is not a Protocol. Handlers
annotate parameters as `MemoryStore` but call methods (`insert_rule`, `insert_entity`,
`insert_checkpoint`, `get_all_engram_slots`, etc.) that exist on the concrete types
but are not declared on the `MemoryStore` name. Pyright rightly cannot verify these.

**Fix (two-step):**

Step 2a — Introduce a `MemoryStoreProtocol` in `infrastructure/memory_store.py`
(or a new `infrastructure/memory_store_protocol.py`) listing the complete public
interface of both concrete stores. Use `typing.Protocol` with `@runtime_checkable`.
The Protocol must include every method called across the 55 handler import sites:
`insert_memory`, `get_memory`, `recall_memories`, `insert_rule`, `get_all_active_rules`,
`insert_entity`, `get_entity_by_name`, `insert_checkpoint`, `get_active_checkpoint`,
`insert_prospective_memory`, `get_active_prospective_memories`, `count_memories`,
`get_hot_embeddings`, `close`, etc. (~30 methods total — enumerate from grep output
across all handler call sites).

Step 2b — Update `get_shared_store` return type to `MemoryStoreProtocol`.
Annotate all handler parameters that accept the store to `MemoryStoreProtocol`.
Both `PgMemoryStore` and `SqliteMemoryStore` implicitly satisfy the Protocol
(they already implement every method); no changes to concrete classes needed.

**Important:** `MemoryStore.__new__` pattern (the factory) is a Move 3 violation
(dynamic dispatch where method body is unknown at call site). The Protocol fix does
not change the runtime behavior; it gives pyright and human readers a sound type
for the returned object. A future refactor could replace the `__new__` factory with
an explicit factory function returning `MemoryStoreProtocol` — that is a separate PR.

**CI after Batch 2:** `reportAssignmentType` blocking at 0; `reportAttributeAccessIssue`
blocking at its post-Batch-2 baseline (~0–10 residual one-offs, to be confirmed after
the run).

---

### Batch 3 — Return-Type Annotation Drift (RC-2)

| Field | Value |
|---|---|
| Scope | `core/emergence_metrics.py`, `core/interference.py`, `handlers/codebase_analyze.py` (primary); scan all `reportReturnType` survivors |
| Estimated errors cleared | ~43 |
| Estimated effort | M (1–2 days) |
| Real bugs likely | Low (annotation is wrong, not the logic) |
| CI change | Set `reportReturnType` to blocking at 0 |

**Fix pattern:** widen return annotations to match actual return expressions.

Examples:
- `def compute_forgetting_metrics(...) -> dict[str, float]` → `dict[str, float | str]`
  (if the dict ever contains string values like status labels).
- `def get_store(...) -> MemoryStore` → `MemoryStoreProtocol` (after Batch 2).

Run `pyright --outputjson | jq '[.generalDiagnostics[] | select(.rule == "reportReturnType")]'`
to enumerate every instance before editing. Fix file-by-file; each file is independent
(no cross-file blast radius for annotation widening).

**Parallelizable:** Batch 3 files are independent of each other and of Batch 4.
After Batch 2 lands, Batches 3 and 4 can run in parallel.

---

### Batch 4 — Residual One-Off Argument/Operator Errors (RC-4)

| Field | Value |
|---|---|
| Scope | All files with surviving `reportArgumentType` / `reportOperatorIssue` after Batch 0 noise removal |
| Estimated errors cleared | ~50 |
| Estimated effort | M (2–3 days) |
| Real bugs likely | Mixed — tuple-key arity mismatches are real; some are cascade from partially resolved types |
| CI change | Set `reportArgumentType` and `reportOperatorIssue` to blocking at 0 |

**Approach:** enumerate after Batch 0 removes noise. Triage each instance:
- Tuple-key arity: fix the call site (pass correct tuple).
- `Unknown`-propagated: confirm they disappear after Batch 2 resolves the store type.
- Genuine: fix the annotation or the logic, whichever is wrong.

---

### Merge Order Summary

```
Batch 0 (CI + config)
    → Batch 1 (Optional guards)
        → Batch 2 (Protocol)
            → Batch 3 (Return drift)   ←┐ parallel
            → Batch 4 (Residual)       ←┘
```

Batches 3 and 4 are independent after Batch 2 lands; assign to separate PRs or
authors.

---

## 4. The First PR — Batch 0 Spelled Out

**PR title:** `chore(types): add pyright CI step and baseline, install deps, suppress stubs-only noise`

**Files changed:**

1. `.github/workflows/test.yml` (or equivalent CI file) — add type-check job:
   ```yaml
   typecheck:
     runs-on: ubuntu-latest
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-python@v5
         with: { python-version: "3.12" }
       - run: pip install pyright
       - run: pip install -e ".[dev,postgresql,codebase]"
       - run: pyright --outputjson > current.json
       - run: python scripts/check_pyright_ratchet.py current.json typecheck-baseline.json
         continue-on-error: true   # removed per-rule as each batch lands
   ```

2. `pyrightconfig.json` (new):
   ```json
   {
     "include": ["mcp_server"],
     "exclude": [".claude", "tests_py", "benchmarks", "scripts"],
     "pythonVersion": "3.10",
     "typeCheckingMode": "basic",
     "reportMissingModuleSource": "none",
     "reportMissingImports": "error"
   }
   ```
   Comment: `reportMissingModuleSource = "none"` — networkx and python-dateutil ship
   stubs-only wheels; pypi source is absent but type correctness is carried by the
   stub packages. Changing this to "warning" or "error" would require installing
   source distributions that don't exist on PyPI.

3. `scripts/check_pyright_ratchet.py` (new, ~40 lines):
   ```python
   """Pyright per-rule ratchet gate.

   Usage: python check_pyright_ratchet.py current.json baseline.json [--blocking rule1 rule2...]

   Fails if any rule in --blocking has a current count > baseline count.
   Reports all rules showing count deltas.
   """
   import json, sys, argparse

   def main():
       p = argparse.ArgumentParser()
       p.add_argument("current")
       p.add_argument("baseline")
       p.add_argument("--blocking", nargs="*", default=[])
       args = p.parse_args()

       with open(args.current) as f:
           current_diags = json.load(f).get("generalDiagnostics", [])
       with open(args.baseline) as f:
           baseline_diags = json.load(f).get("generalDiagnostics", [])

       def count_by_rule(diags):
           out = {}
           for d in diags:
               r = d.get("rule", "unknown")
               out[r] = out.get(r, 0) + 1
           return out

       current = count_by_rule(current_diags)
       baseline = count_by_rule(baseline_diags)
       all_rules = sorted(set(current) | set(baseline))

       failed = []
       for rule in all_rules:
           c, b = current.get(rule, 0), baseline.get(rule, 0)
           delta = c - b
           marker = ""
           if rule in args.blocking and c > b:
               marker = " BLOCKING REGRESSION"
               failed.append(rule)
           elif c < b:
               marker = f" (-{b - c} improved)"
           print(f"  {rule}: {c} (baseline {b}){marker}")

       if failed:
           print(f"\nFAIL: regressions in blocking rules: {failed}")
           sys.exit(1)
       print("\nPASS: no regressions in blocking rules")

   if __name__ == "__main__":
       main()
   ```

4. `typecheck-baseline.json` — generated by running `pyright --outputjson` on the
   branch after steps 1–3 land. Committed as the starting baseline. Regenerate and
   re-commit after each subsequent batch.

**What this PR proves:** the measurement infrastructure works; the real backlog is
437 errors (not 566); the CI job is green (continue-on-error); no source was changed.
Reviewable in under 30 minutes.

---

## 5. Guardrails

These constraints apply to every PR in this plan and cannot be waived:

1. **No `# type: ignore`** — every suppression must be a structural fix or a typed
   Protocol entry, not a silence.

2. **No cast to `Any`** — `cast(Any, x)` is forbidden as a remediation tool. It
   defeats the entire purpose of the exercise and masks real bugs.

3. **`reportMissingImports` is fixed by installing deps, not suppressing** — the CI
   type-check job must run `pip install -e ".[dev,postgresql,codebase]"`. Suppressing
   the rule instead is a contract violation (it hides future missing-dep bugs).

4. **`reportMissingModuleSource`** — the only rule suppressed globally, scoped to
   stubs-only packages (`networkx`, `dateutil`). Justification must appear as a
   comment in `pyrightconfig.json`.

5. **Re-generate and commit the baseline after every batch** — the ratchet is only
   as useful as its baseline is current.

6. **Blocking rules only move to zero** — once a rule is set to blocking, its
   committed baseline count is the ceiling. It may decrease (and the baseline
   should be updated when it does), but never increase.

7. **Concrete stores must not be changed to satisfy the Protocol** — the Protocol
   is additive (declares what is already there). If a method is missing from a
   concrete store, the Protocol was written wrong, not the store.

---

## 6. Per-Batch CI State Summary

| Batch | Blocking rules (post-batch) | Baseline count (each) |
|---|---|---|
| 0 (env) | none yet | ~437 across all rules |
| 1 (Optional guards) | `reportOptionalMemberAccess`, `reportCallIssue` | 0, 0 |
| 2 (Protocol) | + `reportAssignmentType`, `reportAttributeAccessIssue` | 0, ~0 |
| 3 (Return drift) | + `reportReturnType` | 0 |
| 4 (Residual) | + `reportArgumentType`, `reportOperatorIssue` | 0, 0 |
| Done | All rules blocking | 0 total (or documented exceptions) |

---

## 7. Self-Flagged Risks

1. **`MemoryStore.__new__` pattern complexity** — the Protocol definition in Batch 2
   requires enumerating every method called across 55 import sites. Missed methods
   will surface as new `reportAttributeAccessIssue` errors post-Batch-2. Mitigate:
   generate the method list programmatically from pyright's post-Batch-0 output
   before writing the Protocol.

2. **SqliteMemoryStore parity** — `SqliteMemoryStore` may not implement all methods
   that `PgMemoryStore` does (SQLite backend is a testing/fallback path). If it does
   not, the Protocol will expose the gap. Resolution: either add stub implementations
   to SqliteMemoryStore or narrow the Protocol to the common subset and fix callers
   that need PG-only methods to accept `PgMemoryStore` directly.

3. **Cascade resolution after Batch 0** — the 129 noise count is an estimate from
   the taxonomy. The actual post-install count may differ (some env errors may be
   masked by earlier errors in the same file). Re-measure immediately after Batch 0
   and adjust all subsequent estimates before starting Batch 1.
