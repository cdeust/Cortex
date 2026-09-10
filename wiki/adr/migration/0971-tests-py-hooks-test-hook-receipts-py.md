# ADR-0971: tests_py/hooks/test_hook_receipts.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/hooks/test_hook_receipts.py`, original SHA-256 `b8f3fae37940180017302cd5b414b74fe210ea027bfc43e78bc2d61c5b4f87f7`.
Assertions and runtime fixture literals remain unchanged.

## Original docstring, lines 1–18

````text
"""PG-gated tests for the T2 hook receipt channels (decision 4255039).

Falsifiable T2 criteria, per channel:

* the injected stdout carries the ⟦rcpt:id⟧ marker (correction 2);
* the persisted receipt records channel + session_id derived from the
  transcript file basename, NOT the event's divergent session_id field
  (correction 7);
* receipt items mirror exactly the injected payload, in injection order;
* superseded memories never enter the banner/briefing (correction 8).

session_start is exercised in-process (its main() spawns detached
background workers — pipeline reanalyze, consolidate — that a subprocess
test would fire on the host machine). agent_briefing and auto_recall are
exercised end-to-end as subprocesses, mirroring test_auto_recall.py.

Skipped automatically when PG is not reachable (CI without pgvector).
"""
````

## Original docstring, lines 328–346

````text
"""Regression for issue #400.

    ``_SPECIALIST_AGENTS`` is computed once, at module import
    (agent_briefing.py:_load_specialist_agents, called at module scope) —
    so the only faithful reproduction of the reported bug is a fresh
    process that imports the hook with ``CORTEX_CLAUDE_DIR`` already
    pointed at a throwaway tree, the same seam and ordering constraint
    documented for issue #219 (env var must be set before the first
    import; conftest.py's ``_redirect_real_data_roots`` uses the identical
    pattern).

    The throwaway tree here holds exactly ``agents/dispatch.md`` — the
    real shape of ``~/.claude/agents/`` under the plugin-only-dispatch
    architecture (dispatch.md's own frontmatter: "it never does the work
    itself"). Before the fix, only an ABSENT agents directory triggered
    ``_FALLBACK_AGENTS``; a present directory containing only the
    dispatcher yielded a roster of ``{"dispatch"}``, so "engineer" was
    never a known specialist and the briefing silently never fired.
    """
````

## Original comment, lines 390–390

````text
# ── channel enum on live PG (decision 4255039 correction 3) ──────────────
````

