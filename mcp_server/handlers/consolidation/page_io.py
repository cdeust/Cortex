"""Filesystem read/write helpers for the headless authoring worker.

Pure I/O leaf helpers: read source files, parse/rewrite wiki page
frontmatter, render a project tree, and build the anchor-page prompt
(which reads README/manifest/CLAUDE.md from disk). Split out of
``headless_authoring`` to keep that module under the size limit
(Fowler: Move Function). The public import surface remains
``headless_authoring``; these names are imported there and by the
drain/orchestration siblings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .authoring_prompts import _UNTRUSTED_GUARD, _wrap_untrusted

# Hard cap on the project-level context handed to Claude. Bigger
# context = better content but slower call; 16 KB is empirically
# enough for the LLM to write a substantive anchor page.
_CONTEXT_BYTES_CAP = 16000


def _project_source_for_page(
    page_meta: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Resolve the source file path for a file-doc page and read it.

    Returns ``(absolute_path, source_text)`` or ``(None, None)`` when
    the page isn't a file-doc or the source is unreadable. Source
    text is capped at 8 KB to keep prompts within Claude's budget.
    """
    rel = page_meta.get("source_file_path")
    if not rel or not isinstance(rel, str):
        return None, None
    domain = page_meta.get("domain")
    if not domain or not isinstance(domain, str):
        return None, None
    try:
        from mcp_server.core.wiki_coverage import _project_source_root
    except Exception:
        return None, None
    src_root = _project_source_root(domain)
    if not src_root:
        return None, None
    full = os.path.join(src_root, rel)
    try:
        text = Path(full).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return full, None
    # Cap at 8 KB. Files larger than this rarely need their full
    # body — the LLM gets the head + tail with a "[truncated]" marker.
    if len(text) > 8000:
        text = text[:6000] + "\n\n…[truncated middle]…\n\n" + text[-1500:]
    return full, text


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, int]:
    """Lightweight YAML frontmatter parser.

    Returns ``(meta_dict, body, frontmatter_char_count)`` so the
    caller can rewrite the page preserving the frontmatter region.
    """
    if not text.startswith("---"):
        return {}, text, 0
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text, 0
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, Any] = {}
    lines = fm_block.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if ":" not in line:
            idx += 1
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw_s = raw.strip().strip("'\"")
        if not raw_s:
            # Possibly a block list.
            items: list[str] = []
            j = idx + 1
            while j < len(lines):
                peek = lines[j]
                if not peek.startswith((" ", "\t")):
                    break
                strp = peek.lstrip()
                if strp.startswith("- "):
                    items.append(strp[2:].strip().strip("'\""))
                    j += 1
                else:
                    break
            if items:
                meta[key] = items
                idx = j
                continue
            meta[key] = ""
            idx += 1
            continue
        meta[key] = raw_s
        idx += 1
    return meta, body, end + 4


def _rewrite_page(
    page_path: Path,
    *,
    new_body: str,
    new_curation_gaps: list[str],
) -> bool:
    """Rewrite the page on disk with updated body + frontmatter.

    The frontmatter ``curation_gaps`` block is replaced wholesale;
    the rest of the frontmatter is preserved byte-for-byte. The
    body replaces everything after the closing ``---\\n``.
    """
    try:
        text = page_path.read_text(encoding="utf-8")
    except OSError:
        return False

    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    fm_block = text[3:end]
    # Strip any existing curation_gaps block.
    out_lines: list[str] = []
    skip_block = False
    for line in fm_block.splitlines():
        if skip_block:
            if not line.startswith((" ", "\t")):
                skip_block = False
            else:
                continue
        if line.startswith("curation_gaps:"):
            skip_block = True
            continue
        out_lines.append(line)
    if new_curation_gaps:
        out_lines.append("curation_gaps:")
        for g in new_curation_gaps:
            out_lines.append(f"  - {g}")
    new_fm = "\n".join(out_lines).strip()
    # Promote lifecycle as gaps drain. Crude but visible: when there
    # are zero gaps left, lifecycle becomes ``draft`` (ready for
    # human review and promotion to ``accepted``).
    if not new_curation_gaps:
        new_fm = re.sub(
            r"^lifecycle:\s*.*$",
            "lifecycle: draft",
            new_fm,
            count=1,
            flags=re.MULTILINE,
        )
    new_text = "---\n" + new_fm + "\n---\n\n" + new_body.lstrip("\n")
    try:
        page_path.write_text(new_text, encoding="utf-8")
        return True
    except OSError:
        return False


def _read_first(paths: list[Path], cap: int) -> str:
    """Return the first existing file's content, capped at ``cap`` chars."""
    for p in paths:
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            return text[:cap]
    return ""


def _top_level_tree(root: Path, depth: int = 2, cap: int = 200) -> str:
    """Render a shallow top-level tree of ``root`` for prompt context."""
    if not root.is_dir():
        return ""
    lines: list[str] = []
    count = 0

    def walk(p: Path, d: int) -> None:
        nonlocal count
        if d > depth or count >= cap:
            return
        try:
            entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        except OSError:
            return
        for child in entries:
            if count >= cap:
                return
            name = child.name
            if name.startswith((".", "_")):
                continue
            if name in {"node_modules", "dist", "build", "target", "venv", ".venv"}:
                continue
            indent = "  " * d
            kind = "/" if child.is_dir() else ""
            lines.append(f"{indent}- {name}{kind}")
            count += 1
            if child.is_dir():
                walk(child, d + 1)

    walk(root, 0)
    return "\n".join(lines)


def _scope_anchor_prompt(
    domain: str,
    scope_name: str,
    scope_title: str,
    scope_description: str,
    source_root: str,
) -> str:
    """Build the prompt that asks Claude to author a project anchor page.

    Instructs the subprocess Claude to query the codebase intelligence
    MCP tools first (call graph, dependencies, ownership, impact),
    then write the documentation grounded in those results. Falls
    back to file-tree + README context when the tools aren't
    available.

    Pre-condition:  all string parameters are non-empty and well-typed.
    Post-condition: returned prompt includes the security guard header
                    and wraps every project-file block (README, manifest,
                    CLAUDE.md, directory tree, scope_description) in the
                    untrusted delimiter. Bash find/grep fallback
                    instructions are replaced with Grep/Glob tool
                    equivalents that work under the --tools Read,Glob,Grep
                    restriction applied by _claude_invoke.
    """
    src = Path(source_root)
    tree = _top_level_tree(src)
    readme = _read_first(
        [src / n for n in ("README.md", "README.rst", "README.txt", "readme.md")],
        cap=4000,
    )
    manifest = _read_first(
        [
            src / n
            for n in (
                "pyproject.toml",
                "package.json",
                "Cargo.toml",
                "go.mod",
                "build.gradle",
                "settings.gradle",
                "Gemfile",
                "pom.xml",
            )
        ],
        cap=3000,
    )
    claude_md = _read_first(
        [src / "CLAUDE.md", src / ".claude" / "CLAUDE.md"], cap=4000
    )

    # All project-file content is attacker-influenceable — wrap as untrusted.
    extra = (
        f"\n\n## Project README (truncated)\n\n{_wrap_untrusted(readme)}"
        if readme
        else ""
    )
    extra += (
        f"\n\n## Project manifest (truncated)\n\n{_wrap_untrusted(manifest)}"
        if manifest
        else ""
    )
    extra += (
        f"\n\n## CLAUDE.md (truncated)\n\n{_wrap_untrusted(claude_md)}"
        if claude_md
        else ""
    )
    if len(extra) > _CONTEXT_BYTES_CAP:
        extra = extra[:_CONTEXT_BYTES_CAP] + "\n…[truncated]…"

    # scope_description is caller-supplied and may originate from an
    # attacker-influenced registry — wrap as untrusted for consistency.
    safe_scope_description = _wrap_untrusted(scope_description)

    return (
        f"{_UNTRUSTED_GUARD}\n\n"
        f"You are authoring a wiki anchor page for the project `{domain}`.\n\n"
        f"The page you must produce is the **{scope_title}** anchor "
        f"(scope: `{scope_name}`). The scope description is:\n\n"
        f"{safe_scope_description}\n\n"
        f"## Ground your writing in codebase intelligence FIRST\n\n"
        f"Before drafting the page, use whatever codebase-intelligence "
        f"tools are available to extract structural facts about the "
        f"project. Try in this order (skip silently if a tool is "
        f"unavailable):\n\n"
        f"1. **`codebase_analyze`** / **`codebase_query`** / "
        f"**`codebase_scan`** on `{source_root}` — call graph, "
        f"module dependencies, file/symbol counts.\n"
        f"2. **`codebase_ownership`** — who edits what, hot files.\n"
        f"3. **`codebase_bus_factor`** — concentration risk per file.\n"
        f"4. **`codebase_dead_code`** — unused exports.\n"
        f"5. **`Grep`** as a fallback — search for function signatures, "
        f"module imports, and symbol references within the project.\n"
        f"6. **`Glob`** to enumerate files matching a pattern "
        f"(e.g. `{source_root}/**/*.py`) when you need a file list.\n"
        f"7. **`Read`** the README, key entry-point files, and any "
        f"`docs/` directory inside the project.\n\n"
        f"Then write the anchor page grounded in what you actually "
        f"observed. Cite specific files, directories, modules, and "
        f"call relationships — NOT generic prose.\n\n"
        f"## What I want from you\n\n"
        f"Write the FULL Markdown body of the anchor page (no frontmatter — "
        f"I'll add it). It must be:\n\n"
        f"* Substantive (target 3-8 KB of real prose).\n"
        f"* Specific to THIS project — every claim grounded in either "
        f"the codebase analysis tool output or a file you actually read.\n"
        f"* Structured: lead paragraph saying what the page is for, "
        f"then 4-7 substantive sections.\n"
        f"* Honest: if the project genuinely has nothing for this scope "
        f'(e.g. no MCP integration), write a one-paragraph "this '
        f'project does not currently expose this surface" page; '
        f"don't fabricate.\n"
        f"* Cross-link to siblings using `[[reference/{domain}/<other>]]` "
        f"notation when relevant.\n\n"
        f"Output ONLY the Markdown body. No preamble. No code fence around it.\n\n"
        f"## Project context (use as starting hint, not the full picture)\n\n"
        f"Domain: `{domain}`\n"
        f"Source root: `{source_root}`\n\n"
        f"### Top-level structure\n\n"
        f"{_wrap_untrusted(tree)}{extra}"
    )


def _write_anchor_page(
    wiki_root: Path,
    domain: str,
    scope_name: str,
    suggested_kind: str,
    suggested_path: str,
    body_markdown: str,
    today: str,
) -> Path | None:
    """Write the authored anchor page with proper frontmatter."""
    page_path = wiki_root / suggested_path
    title_map = {
        "product-overview": "Product overview",
        "architecture": "Architecture overview",
        "services": "Services & components",
        "code-walkthrough": "Code walkthrough",
        "api": "Public API surface",
        "data-flow": "Data flow",
        "commands": "Commands & CLI",
        "mcp": "MCP integration",
        "tools": "Tooling & dependencies",
        "ci-cd": "CI / CD",
        "ai-usage": "AI usage",
        "operations": "Operations & runbooks",
        "prd": "Product requirements",
        "decisions": "Decisions",
        "onboarding": "Onboarding",
    }
    title = f"{domain} — {title_map.get(scope_name, scope_name)}"
    frontmatter = (
        "---\n"
        f"title: {title}\n"
        f"kind: {suggested_kind}\n"
        f"domain: {domain}\n"
        f"scope: {scope_name}\n"
        "status: living\n"
        "authored_by: headless-authoring-worker\n"
        "provenance: auto-authored\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"last_reviewed: {today}\n"
        "---\n\n"
    )
    try:
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(
            frontmatter + body_markdown.strip() + "\n", encoding="utf-8"
        )
        return page_path
    except OSError:
        # PermissionError (an OSError subclass) on mkdir/write must not propagate:
        # this runs under asyncio.gather(return_exceptions=False), so an escape
        # aborts the entire anchor phase. Swallow → skip this one page.
        return None
