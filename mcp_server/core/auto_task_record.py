"""Auto-spawn task-record ADRs from completed session work.

User direction 2026-05-18: every new task / bug / feature should be
treated with the same detailed approach. This module is the
machinery that turns a session ending with substantive work into a
draft ADR carrying the task-record contract (Entry / Mandatory
elements / How / Result / Serves) — the same shape humans use, so
nothing is below the level of importance.

The draft is NOT a finished page. It pulls together:

  * Commit messages made during the session (the user-stated intent).
  * Memories tagged with decision / lesson / fix during the session
    (the things the user explicitly chose to capture).
  * Changed files (the artifact of the work).
  * A frontmatter ``lifecycle: draft`` so the conversational LLM
    refines it on the next session via ``curate_wiki``'s re-author
    queue.

Pure logic — the handler ``record_session_end`` invokes
``build_task_record`` with the inputs already in hand, then writes
the page via the existing wiki write path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Threshold below which a session isn't substantive enough to warrant a
# task-record. Tuned so a quick browse / read-only session doesn't
# pollute the wiki, but any session that produced commits, edits, or
# explicit memories above the floor gets documented.
MIN_COMMITS_FOR_RECORD: int = 1
MIN_MEMORIES_FOR_RECORD: int = 2
MIN_TOOLS_FOR_RECORD: int = 5


@dataclass
class TaskRecordInputs:
    """Bundle of session evidence the auto-ADR builder needs.

    Kept as a DTO so the handler composes whatever it has without a
    long parameter list (Clean Architecture §4.4).
    """

    session_id: str
    domain: str
    cwd: str
    duration_seconds: float | None
    turn_count: int | None
    commits: list[dict] = field(default_factory=list)
    # Each commit: {"hash": str, "message": str, "files": [str], "timestamp": str}
    memories: list[dict] = field(default_factory=list)
    # Each memory: {"content": str, "tags": list[str], "created_at": str}
    changed_files: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)


@dataclass
class TaskRecord:
    """The synthesised draft."""

    slug: str
    title: str
    domain: str
    suggested_path: str  # adr/<domain>/<NNNN>-<slug>.md
    frontmatter: dict[str, str]
    body: str


_SLUG_SAFE = re.compile(r"[^a-z0-9]+")
_FIRST_LINE_RE = re.compile(r"^.+", re.MULTILINE)


def _slugify(text: str, max_len: int = 60) -> str:
    s = _SLUG_SAFE.sub("-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "unnamed"


def _derive_title(inputs: TaskRecordInputs) -> str:
    """Pick a short specific title from the session evidence.

    Priority:
      1. First commit message's subject line — usually states intent.
      2. First memory tagged ``decision``/``lesson`` — the user's
         explicit capture.
      3. Tool-heavy session with no commits / decision memories falls
         back to a generic title; the LLM refines it on the next pass.
    """
    if inputs.commits:
        msg = inputs.commits[0].get("message") or ""
        first = _FIRST_LINE_RE.search(msg)
        if first:
            return first.group(0).strip()[:120]
    for m in inputs.memories:
        tags = m.get("tags") or []
        if any(t in {"decision", "lesson", "adr"} for t in tags):
            content = (m.get("content") or "").strip()
            first = _FIRST_LINE_RE.search(content)
            if first:
                return first.group(0).strip()[:120]
    return f"Session work — {inputs.cwd or inputs.domain}"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def is_substantive(inputs: TaskRecordInputs) -> bool:
    """True when the session produced enough evidence to deserve an ADR.

    The thresholds are deliberately lenient: anything with a commit
    earns a record. Tool-heavy read-only sessions need a fair amount of
    activity (5+ tools) AND some captured memories.
    """
    if len(inputs.commits) >= MIN_COMMITS_FOR_RECORD:
        return True
    if (
        len(inputs.memories) >= MIN_MEMORIES_FOR_RECORD
        and len(inputs.tools_used) >= MIN_TOOLS_FOR_RECORD
    ):
        return True
    return False


def _section_entry(inputs: TaskRecordInputs) -> str:
    """Draft the Entry section from commits + early memories.

    Picks the highest-signal user-stated intent — typically the first
    commit's subject — and frames it as the trigger.
    """
    if inputs.commits:
        msg = inputs.commits[0].get("message", "").strip()
        return (
            f"Session triggered by the following intent (first commit "
            f"in session):\n\n> {msg.splitlines()[0] if msg else '(no message)'}\n\n"
            f"Total commits in this session: {len(inputs.commits)}."
        )
    for m in inputs.memories[:5]:
        tags = m.get("tags") or []
        if any(t in {"decision", "lesson", "todo", "bug"} for t in tags):
            content = (m.get("content") or "").strip()
            head = content.splitlines()[0] if content else "(no content)"
            return f"Captured at session start: {head}"
    return (
        f"Session in `{inputs.domain}` produced "
        f"{len(inputs.tools_used)} tool invocations and "
        f"{len(inputs.memories)} memory captures. The LLM should "
        "refine this Entry by reading those memories and the commits "
        "before publishing."
    )


# source: pre-existing tuned values, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MAX_COMMITS_LISTED = 10  # draft-body cap; the rest is summarised as a count
_MAX_FILES_LISTED = 20  # draft-body cap; the rest is summarised as a count


def _section_how(inputs: TaskRecordInputs) -> str:
    """Draft the How section from the commit list + changed files."""
    lines: list[str] = []
    if inputs.commits:
        lines.append("Implementation moves (commit-by-commit):\n")
        for c in inputs.commits[:_MAX_COMMITS_LISTED]:
            hsh = (c.get("hash") or "")[:8]
            msg = (
                (c.get("message") or "").splitlines()[0]
                if c.get("message")
                else "(no message)"
            )
            lines.append(f"- `{hsh}` — {msg}")
        if len(inputs.commits) > _MAX_COMMITS_LISTED:
            lines.append(
                f"- … and {len(inputs.commits) - _MAX_COMMITS_LISTED} more commits."
            )
    if inputs.changed_files:
        lines.append("\nFiles touched:")
        for f in inputs.changed_files[:_MAX_FILES_LISTED]:
            lines.append(f"- `{f}`")
        if len(inputs.changed_files) > _MAX_FILES_LISTED:
            lines.append(
                f"- … and {len(inputs.changed_files) - _MAX_FILES_LISTED} more files."
            )
    if not lines:
        lines.append(
            "(no commits or file changes recorded — session was likely "
            "read-only. LLM should describe the analysis path from the "
            "session memories.)"
        )
    return "\n".join(lines)


def _section_result(inputs: TaskRecordInputs) -> str:
    """Draft the Result section — point at the artifacts."""
    if not inputs.commits:
        return (
            "(no commits — work product is whatever the session memories "
            "and tool outputs describe. LLM should cite specifically.)"
        )
    latest = inputs.commits[-1]
    hsh = (latest.get("hash") or "")[:8]
    msg = (latest.get("message") or "").splitlines()[0]
    return (
        f"Latest commit at session end: `{hsh}` — {msg}\n\n"
        f"Total: {len(inputs.commits)} commits across "
        f"{len(inputs.changed_files)} files."
    )


def _section_mandatory() -> str:
    """The mandatory-elements section — a draft framing the LLM refines."""
    return (
        "_The LLM should fill this from the project's CLAUDE.md, the "
        "coding standards file, and any explicit invariants the session "
        "memories captured. Typical constraints to enumerate:_\n\n"
        "- Clean Architecture layer rule (core ← shared, infra → core)\n"
        "- SOLID — single responsibility, dependency inversion\n"
        "- Source-citation discipline — every algorithm/constant has a "
        "paper or benchmark\n"
        "- File-size limits (300 lines per file, 40 per method)\n"
        "- No SQLite / no in-memory fallbacks (Cortex constraint)\n"
        "- Existing PG schema invariants if the work touched migrations"
    )


def _section_serves(inputs: TaskRecordInputs) -> str:
    """The serves section — placeholder for the LLM."""
    return (
        "_The LLM should fill this from the session intent. Typical "
        "anchors:_\n\n"
        f"- Which subsystem in `{inputs.domain}` depends on this work?\n"
        "- What user-visible behaviour does it support?\n"
        "- Which invariant or contract is upheld by it?\n"
        "- What downstream task does it unblock?"
    )


def build_task_record(
    inputs: TaskRecordInputs,
    *,
    adr_number: int,
) -> TaskRecord:
    """Compose the task-record from the inputs.

    ``adr_number`` is the next ADR identifier for the project — caller
    counts existing ``adr/<domain>/NNNN-*.md`` and passes the next value.
    The body carries every mandatory section from the ADR template even
    when the corresponding evidence is thin; the LLM finishes the draft
    on the next session via ``curate_wiki`` re-author flow.
    """
    title = _derive_title(inputs)
    slug = _slugify(title)
    filename = f"{adr_number:04d}-{slug}.md"
    suggested_path = f"adr/{inputs.domain}/{filename}"

    today = _today_iso()
    frontmatter = {
        "id": f"{adr_number:04d}",
        "title": title,
        "kind": "adr",
        "domain": inputs.domain,
        "status": "proposed",
        "lifecycle": "draft",
        "audience": "developer",
        "provenance": "auto-generated",
        "authored_by": "auto-task-record",
        "session_id": inputs.session_id,
        "date": today,
        "created": today,
        "updated": today,
        "last_reviewed": today,
    }
    fm_lines = (
        "---\n" + "\n".join(f"{k}: {v}" for k, v in frontmatter.items()) + "\n---\n"
    )

    body_parts: list[str] = [
        fm_lines,
        f"\n# ADR-{adr_number:04d}: {title}",
        "\n## Status\n\nproposed (auto-draft — LLM to verify and flip to "
        "`accepted` once refined)",
        f"\n## Entry\n\n{_section_entry(inputs)}",
        f"\n## Mandatory elements\n\n{_section_mandatory()}",
        f"\n## How\n\n{_section_how(inputs)}",
        f"\n## Result\n\n{_section_result(inputs)}",
        f"\n## Serves\n\n{_section_serves(inputs)}",
        "\n## Alternatives considered\n\n_The LLM should enumerate "
        "alternatives discussed in session memories tagged `decision` / "
        "`alternative` and any rejected approaches captured in commit "
        "messages._",
        "\n## References\n\n"
        + (
            "Memories captured during this session:\n\n"
            + "\n".join(
                f"- `{(m.get('created_at') or '')[:10]}` — "
                f"{(m.get('content') or '').splitlines()[0][:160]}"
                for m in inputs.memories[:8]
            )
            if inputs.memories
            else "_no memories captured in session; the LLM should look up "
            "related entries via `recall`._"
        ),
    ]
    body = "\n".join(body_parts) + "\n"

    return TaskRecord(
        slug=slug,
        title=title,
        domain=inputs.domain,
        suggested_path=suggested_path,
        frontmatter=frontmatter,
        body=body,
    )
