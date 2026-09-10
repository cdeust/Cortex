# ADR-0495: mcp_server/hooks/post_tool_capture.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/post_tool_capture.py`; original SHA-256 `e91d004f10fd6615dffc002f99cf2f6e83ada49312fcf49576a816000496ed29`.

## Original docstring, lines 2–14

````text
"""Claude Code PostToolUse hook — captures significant tool outputs as
memories after each tool call, so graph ingestion is zero-friction.

Filters: tool kind (high-value vs light-value vs conditional), output
length, content-signal keywords. High-value tools (Edit/Write/Bash/
MultiEdit/NotebookEdit) store the full truncated output; light-value
tools (Read/NotebookRead/Glob/Grep) record only the input reference to
reduce payload size. Invariants: idempotent via the
predictive-coding write gate, stderr-only logging.

Install via ``~/.claude/settings.json``'s PostToolUse hook pointed at
``python3 -m mcp_server.hooks.post_tool_capture``.
"""
````

## Original comment, lines 36–42

````text
# Tools we capture for graph visibility only. We record the input
# reference (file_path / pattern / command / URL), omitting the tool output.
# This reduces the payload; model startup and write-gate work still
# contribute to latency. W2 launcher measurements observed seconds of CPU
# in a cold capture even for Read; a short payload alone cannot bound it.
# The workflow graph uses these references to record every file touched,
# including files that were only read during a live session.
````

## Original comment, lines 59–68

````text
# 2026-05-17 (user directive: "Truncated info are prohibited"):
# auto-capture stores the FULL tool output. Truncation destroys the
# substrate halo retrieval needs — a 20k-char Edit diff cropped to 4k
# loses the actual code change. The directive itself anticipated
# "filesystem-backed references" as the remedy if the corpus grows too
# large. 2026-06-10 (user directive, docs/provenance/bounded-io-phase2-design.md):
# outputs above GIST_BUDGET are now stored full to a content-addressed
# artifact file and the memory body keeps a deterministic gist + a pointer
# line. This is NOT truncation — nothing is dropped; the raw output is one
# `Read` away — and it removes the ts_rank_cd length-frequency bias (M2).
````

## Original comment, lines 70–73

````text
# Keywords that signal high-value content. Canonical home is
# core/gist_extraction.HIGH_VALUE_PATTERNS (moved there so the hook imports
# from core, the legal layer direction). Re-exported under the historical
# name for any in-repo reference.
````

## Original comment, lines 97–105

````text
# issue #365: these are the NETWORK tools, so their output is
        # off-machine content. The predicate deliberately does NOT read that
        # output: keying capture on `kw in output_lower` let a fetched page
        # decide whether it got written to long-term memory by including one
        # of _HIGH_VALUE_PATTERNS, and session_start replays stored memories
        # verbatim into later sessions. The rule is now the same fixed,
        # content-independent one the high-value tools use — a length floor —
        # and the resulting memory carries ORIGIN_NETWORK so the write gate
        # refuses it the content-derived bypasses (core/write_gate).
````

## Original docstring, lines 146–154

````text
"""Build a structured memory string. Light-value tools record only
    the input reference to reduce the stored payload.

    2026-05-17: ``_normalize_output`` now returns Markdown-ready text
    for dict tool responses (with its own fenced ``stdout:`` /
    ``stderr:`` sections). Detect that here and don't wrap it again —
    nested fences break rendering. Only wrap raw string output, which
    is the case for tools whose response is a flat string.
    """
````

## Original docstring, lines 204–213

````text
"""Build tags from tool name and output signals.

    2026-05-17: the ``decision`` tag was previously added whenever the
    raw tool output contained the substring "selected"/"switched"/etc.
    Edit/Bash dumps routinely contain those words inside diffs or stdout,
    so every auto-capture got promoted to wiki kind="adr" and rendered
    as ``Decision: <first line of dump>``. Real ADRs come from explicit
    ``remember`` calls with ``source="decision"``, not from PostToolUse
    keyword scanning — the tag is removed here.
    """
````

## Original docstring, lines 230–250

````text
"""Normalize tool output to a HUMAN-READABLE string.

    2026-05-17 (user directive: "stdout should never be a single line,
    intelligible and readable documentation in natural way"). Previously
    every dict response went through ``json.dumps`` which encoded real
    newlines as the two-character ``\\n`` escape sequence — so a multi-
    line grep output rendered in the wiki as one literal-escape-laden
    string instead of a readable code block.

    Tool-response shapes handled here:

      * ``Bash``: ``{"stdout": "...", "stderr": "...", "interrupted": bool,
        ...}`` → renders stdout (and stderr if non-empty) as fenced
        sections with real newlines preserved.
      * ``Edit``/``Write``/``MultiEdit``: ``{"filePath": "...",
        "oldString": "...", "newString": "..."}`` → renders as a
        before/after section with real newlines.
      * Generic dict / list → json.dumps with ``indent=2`` so newlines
        between fields survive at least one level of structure.
      * Anything else → ``str()``.
    """
````

## Original comment, lines 317–317

````text
# The producing tool remains out-of-band provenance (issue #365).
````

## Original comment, lines 361–361

````text
# source: owner decision, green-remediation W3-1b: full when unset.
````

## Original comment, lines 376–377

````text
# issue #398: close every store before interpreter finalization, including
    # exceptions/SystemExit, only when this event could construct a store.
````

## Original comment, lines 412–413

````text
# Scrub the assembled content (catches secrets in the Bash command
    # reference line and any other structural fragments).
````

