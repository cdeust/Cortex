"""Session execution-trace reconstruction (pure core logic).

Turns one Claude Code session's ordered event stream (user prompts +
assistant tool calls) into a causal chain graph: a time-ordered spine of
prompt/action nodes linked by ``next`` edges, with each action linked to
the files it touched (verb-tagged: read / edit / write / run).

This is the L2 level of the domain-split trace graph:

    domain -> session -> [prompt -> action -> action -> ...] -> file

Pure logic — no I/O. The infrastructure layer feeds it an ordered event
list (see ``infrastructure.trace_source.iter_session_events``); this
module owns the node/edge vocabulary the frontend renders.

Node kinds emitted: ``prompt``, ``action``, ``file``.
Edge kinds emitted: ``step`` (session -> first event), ``next`` (time
order along the spine), and the file verbs ``read`` / ``edit`` /
``write`` / ``run``.
"""

from __future__ import annotations

import re
from typing import Any

# ── File-path extraction from tool inputs (pure) ────────────────────────
# Tools whose ``input`` carries an explicit file path. Mirrors the set the
# legacy ingest used, lifted here so the trace owns one definition.
_FILE_INPUT_TOOLS = frozenset(
    {
        "Edit",
        "Write",
        "Read",
        "MultiEdit",
        "NotebookEdit",
        "NotebookRead",
        "Glob",
        "Grep",
    }
)

# Path-like tokens inside Bash commands (cat / tail / head / vim ...): /abs,
# ~/rel, or ./rel with at least 3 chars past the prefix.
_BASH_PATH_RE = re.compile(r"(?:^|[\s=])((?:\.{1,2}/|~/|/)[^\s`'\"]{3,})")

# Tool name -> the verb describing what it did to a file.
_TOOL_VERB = {
    "Read": "read",
    "NotebookRead": "read",
    "Grep": "read",
    "Glob": "read",
    "Edit": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Write": "write",
    "Bash": "run",
}


def extract_file_refs(tool: str, inp: dict) -> list[tuple[str, str]]:
    """Return ``[(verb, path), ...]`` for every file this tool touched.

    Pure: depends only on the tool name + its input dict. Bash paths are
    parsed from the command text; deduped within one call so a command
    referencing the same path twice yields one edge.
    """
    inp = inp or {}
    verb = _TOOL_VERB.get(tool, "read")
    refs: list[tuple[str, str]] = []
    if tool in _FILE_INPUT_TOOLS:
        for key in ("file_path", "path", "notebook_path"):
            fp = inp.get(key)
            if fp:
                refs.append((verb, str(fp)))
    if tool == "Bash":
        cmd = str(inp.get("command") or "")
        seen: set[str] = set()
        for m in _BASH_PATH_RE.finditer(" " + cmd):
            tok = m.group(1).rstrip(".,;:)'\"")
            if tok not in seen and tok.startswith(("/", "~/", "./", "../")):
                seen.add(tok)
                refs.append(("run", tok))
    return refs


def _short(text: str, n: int = 60) -> str:
    s = " ".join(str(text or "").split())
    return s[: n - 1] + "…" if len(s) > n else s


def _action_label(tool: str, inp: dict) -> str:
    """Human-readable one-liner for an action node."""
    inp = inp or {}
    if tool == "Bash":
        return _short(inp.get("command") or "bash", 48)
    if tool in ("Task", "Agent"):
        return _short(inp.get("subagent_type") or "agent", 32)
    for key in ("file_path", "path", "notebook_path", "pattern", "query"):
        if inp.get(key):
            return _short(inp[key], 48)
    return tool


def _file_node(path: str) -> dict:
    base = path.replace("\\", "/").rstrip("/").split("/")[-1] or path
    return {
        "id": f"file:{path}",
        "kind": "file",
        "type": "file",
        "label": base,
        "path": path,
        # NOTE: no ``collapsed`` flag. The force-graph renderer hides any
        # node with ``collapsed`` unless its ``_parentId`` is in the
        # expanded set; trace controls visibility by what it FETCHES
        # (file nodes only arrive when a session is expanded), so a
        # collapsed flag here would make every file invisible. The L3
        # AST/impact/git drill is triggered on click, not via this flag.
        "drillable": True,
    }


def build_chain(
    events: list[dict[str, Any]], session_id: str, since: int = 0
) -> dict[str, Any]:
    """Build the L2 causal-chain delta for one session.

    Args:
        events: ordered list (by timestamp then line) of
            ``{"kind": "prompt"|"action", "tool"?, "input"?, "text"?,
               "ts"?, "line"?}``.
        session_id: the parent session node id (``session:<sid>``) the
            spine attaches to via a ``step`` edge.
        since: number of chain STEPS the client already holds. Events
            producing steps ``< since`` are replayed only for spine
            bookkeeping (so the first new ``next`` edge links to the
            existing node ``{sid}:e{since-1}``) but are NOT re-emitted.
            ``since=0`` returns the whole chain (initial expand);
            ``since=N`` returns only the live tail (poll for new work).
            Node ids are deterministic + dedup-safe, so an over-large
            ``since`` simply yields an empty delta.

    Returns ``{"nodes": [...], "edges": [...], "next_since": int}`` —
    ``next_since`` is the step count the client should send next poll.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    files_seen: set[str] = set()
    session_node = f"session:{session_id}"

    prev_id: str | None = None
    step = 0
    for ev in events:
        kind = ev.get("kind")
        ts = ev.get("ts")
        # Replay-skip: advance step + prev_id without emitting, so the
        # first emitted node's ``next`` edge points at the node the
        # client already has.
        emit = step >= since
        if kind == "prompt":
            text = ev.get("text") or ""
            if not text.strip():
                continue
            nid = f"{session_id}:e{step}"
            if not emit:
                prev_id = nid
                step += 1
                continue
            nodes.append(
                {
                    "id": nid,
                    "kind": "prompt",
                    "type": "prompt",
                    "label": _short(text, 60),
                    "full": text[:4000],
                    "ts": ts,
                    "seq": step,  # execution order — drives the timeline spine
                    "session_id": session_id,
                    "domain_id": session_node,
                }
            )
        elif kind == "action":
            tool = ev.get("tool") or ev.get("name") or "tool"
            inp = ev.get("input") or {}
            nid = f"{session_id}:e{step}"
            if not emit:
                prev_id = nid
                step += 1
                continue
            nodes.append(
                {
                    "id": nid,
                    "kind": "action",
                    "type": "action",
                    "tool": tool,
                    "label": _action_label(tool, inp),
                    "ts": ts,
                    "seq": step,  # execution order — drives the timeline spine
                    "session_id": session_id,
                    "domain_id": session_node,
                }
            )
            # action -> file verb edges (+ file nodes once each)
            for verb, path in extract_file_refs(tool, inp):
                fid = f"file:{path}"
                if path not in files_seen:
                    files_seen.add(path)
                    nodes.append(_file_node(path))
                edges.append(
                    {
                        "id": f"{nid}->{fid}",
                        "source": nid,
                        "target": fid,
                        "kind": verb,
                        "type": verb,
                    }
                )
        else:
            continue

        # spine: session -> first event (step), then event -> event (next)
        if prev_id is None:
            edges.append(
                {
                    "id": f"{session_node}->{nid}",
                    "source": session_node,
                    "target": nid,
                    "kind": "step",
                    "type": "step",
                }
            )
        else:
            edges.append(
                {
                    "id": f"{prev_id}->{nid}",
                    "source": prev_id,
                    "target": nid,
                    "kind": "next",
                    "type": "next",
                }
            )
        prev_id = nid
        step += 1

    return {"nodes": nodes, "edges": edges, "next_since": step}


__all__ = ["build_chain", "extract_file_refs"]
