# ADR-0446: mcp_server/handlers/seed_project_constants.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/seed_project_constants.py`; original SHA-256 `04eddcd30110d0fb913e0e7c6c5f97baefe309d528873f7aefb06b3ff0bb9db6`.

## Original comment, lines 98–104

````text
# 2026-05-17 (user feedback): seed_project was producing wiki pages
    # titled ``Spec: Entry point: .claude/worktrees/agent-a0ceb782/...``
    # because per-agent git worktrees were treated as real source trees.
    # A worktree is a transient build of the same code — seeding it
    # creates N duplicate sets of stub pages. Same for ``.claude/``
    # itself (settings, hooks, agent state) and for ``deps/`` vendored
    # third-party trees we don't author.
````

## Original comment, lines 117–120

````text
# 2026-05-17: path-fragment predicate complementing IGNORE_DIRS. Returns
# True if the absolute path looks like a pytest temp fixture root or a
# transient agent worktree — both should be silently rejected by
# seed_project before any pages are generated.
````

