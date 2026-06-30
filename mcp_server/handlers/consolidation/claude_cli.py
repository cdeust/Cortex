"""``claude -p`` argv + child-environment construction.

Split out of ``headless_authoring`` to keep that module under the 500-line
size limit (Fowler: Extract Function). These are pure builders — no
subprocess, no I/O beyond reading ``os.environ``. The async invocation that
consumes them (``_claude_invoke``) stays in ``headless_authoring`` because it
is the patchable seam tests target.

Patchability contract: the runtime knobs (``CORTEX_HEADLESS_AGENTS``,
``CORTEX_HEADLESS_AUTH``) and ``_CLAUDE_BIN`` are read off the root module at
CALL time, so ``monkeypatch.setattr(headless_authoring, ...)`` is observed —
matching the scanner/drain sibling pattern documented in
``headless_authoring``'s module docstring.

Security model (audit B-1) — the argv differs by mode:

Agents mode (``CORTEX_HEADLESS_AGENTS=1``, the default) — load the user's
zetetic agent roster and let the top-level authoring agent delegate read-only
analysis to specialists. TWO INDEPENDENT ENFORCING CONTROLS keep it safe:

  Control A — ``--setting-sources user``
      Loads ONLY the user's settings/agents/hooks. Project and local sources
      are NOT loaded, so a malicious repository cannot inject
      ``permissions.allow:["Bash"]`` or a malicious hook — the original B-1
      project-injection vector stays closed. The roster that DOES load is the
      user's own, authored by the user, hence trusted: the threat model here
      is malicious *source material being documented*, not malicious *user
      config*. Verified empirically against claude CLI 2.1.197 (2026-06-30):
      paper-writer / architect / feynman / zetetic-team-subagents:* load;
      project/local agents do not.

  Control B — ``--disallowedTools "Write,Edit,Bash,NotebookEdit"``
      A HARD DENY ceiling. Verified empirically (2026-06-30) to PROPAGATE to
      spawned subagents: a delegated write-capable ``engineer`` received only
      Read/Glob/Grep + MCP; a top-level ``Write`` attempt returned "not
      enabled" and produced no file. So the roster can analyse but never
      write or execute, transitively. ``--tools "Read,Glob,Grep,Task"`` adds
      ``Task`` (delegation) to the read-only built-in set.

  Hooks side effect: ``--setting-sources user`` also loads the user's hooks.
      They are neutralised by ``CORTEX_HEADLESS_AUTHORING_CHILD=1`` (see
      ``_subprocess_env`` and ``mcp_server.hooks._headless_guard``).

  MCP note: ``--setting-sources user`` also loads the user's MCP servers,
      which the authoring prompts use for grounding (codebase_context etc.).
      ``--disallowedTools`` does not gate MCP tools, but those servers are the
      user's own (trusted). A write-capable MCP tool call is possible but is
      soft pollution, not a sandbox breach, and the prompts never request it.

Solo mode (``CORTEX_HEADLESS_AGENTS=0``) — hardened config isolation:

  Control — ``--safe-mode``
      Disables CLAUDE.md, skills, plugins, hooks, MCP servers, custom
      commands/agents, and project/user settings. Same malicious-settings and
      malicious-hook defence, no roster, no Task tool. Chosen over ``--bare``
      deliberately: ``--bare`` forces API-key billing (OAuth/keychain never
      read), whereas ``--safe-mode`` keeps the subscription intact.
      ``--tools "Read,Glob,Grep"`` is the read-only built-in set.

Common to both modes:

  ``--output-format json`` — single JSON object with ``result`` (assistant
      text) and ``total_cost_usd`` (client-side spend). ``--print`` /
      ``--no-session-persistence`` — one-shot, no session file.

  ``--add-dir <source_root>`` (when given) — EXTENDS readable scope; it does
      NOT confine reads. Residual read-exfiltration risk is unchanged from the
      pre-agents design; full FS isolation would need ``--sandbox`` (out of
      scope). NOTE: ``--add-dir`` is variadic (``<directories...>``); a
      positional prompt placed after it is swallowed as a second directory and
      the CLI errors "Input must be provided". The prompt is therefore passed
      via STDIN (see ``_claude_invoke``), never as a positional argument —
      removing all argv-ordering fragility.

  Advisory (NOT counted as enforcing): the ``_wrap_untrusted`` delimiter in
      ``authoring_prompts`` demotes file content to DATA. Defence-in-depth
      only — it relies on model instruction-following, not a hard sandbox.

Sources: https://code.claude.com/docs/en/cli-reference
         https://code.claude.com/docs/en/headless
"""

from __future__ import annotations

import os

from . import headless_authoring as _root

# Anthropic credential keys stripped from the child env in subscription mode.
_API_CREDENTIAL_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

# Stamped into every authoring child's env so the user's Cortex hooks — loaded
# by ``--setting-sources user`` in agents mode — early-exit instead of running
# (recursion + pollution guard). See ``mcp_server.hooks._headless_guard``. Set
# unconditionally: harmless in solo mode (``--safe-mode`` disables hooks), load-
# bearing in agents mode.
_HEADLESS_CHILD_FLAG = "CORTEX_HEADLESS_AUTHORING_CHILD"

# Hard tool-deny ceiling applied in agents mode. Propagates to subagents.
_AGENTS_DISALLOWED_TOOLS = "Write,Edit,Bash,NotebookEdit"


def _subprocess_env() -> dict[str, str]:
    """Child env for ``claude -p``: auth method + hook-neutralising flag.

    Default ``CORTEX_HEADLESS_AUTH=subscription`` strips API-key credentials
    so the CLI uses the logged-in subscription (no API charge). Setting
    ``CORTEX_HEADLESS_AUTH=api`` passes the parent env through unchanged, so a
    present ``ANTHROPIC_API_KEY`` bills the API — an explicit user opt-in.

    In both cases ``CORTEX_HEADLESS_AUTHORING_CHILD=1`` is set so the user's
    Cortex hooks (loaded by ``--setting-sources user`` in agents mode) no-op
    inside the child — preventing the consolidation-recursion and
    memory-pollution that running them there would cause.
    """
    mode = os.getenv("CORTEX_HEADLESS_AUTH", "subscription").strip().lower()
    if mode == "api":
        env = dict(os.environ)
    else:
        env = {k: v for k, v in os.environ.items() if k not in _API_CREDENTIAL_KEYS}
    env[_HEADLESS_CHILD_FLAG] = "1"
    return env


def _build_argv(source_root: str | None) -> list[str]:
    """Build the ``claude -p`` argv for the active mode.

    Reads ``_root.CORTEX_HEADLESS_AGENTS`` at call time (patchable). See this
    module's docstring for the per-mode security argument. The prompt is NOT
    part of the argv — it is fed via STDIN by ``_claude_invoke`` (the variadic
    ``--add-dir`` would otherwise swallow a trailing positional prompt).

    Post-condition: returns the option-only argv; the tool surface is
                    read-only in both modes (no Write/Edit/Bash).
    """
    argv = [_root._CLAUDE_BIN, "--print", "--no-session-persistence"]
    if _root.CORTEX_HEADLESS_AGENTS:
        # Agents mode: roster + Task delegation under a hard write/exec ceiling.
        argv += [
            "--setting-sources",
            "user",
            "--tools",
            "Read,Glob,Grep,Task",
            "--disallowedTools",
            _AGENTS_DISALLOWED_TOOLS,
        ]
    else:
        # Solo mode: hardened config isolation, no roster, no delegation.
        argv += ["--safe-mode", "--tools", "Read,Glob,Grep"]
    argv += ["--output-format", "json"]
    if source_root:
        # Extends readable scope to include source_root; does NOT confine.
        argv += ["--add-dir", source_root]
    return argv
