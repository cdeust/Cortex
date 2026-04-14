"""Phase 10 — Pandoc-backed wiki page export.

Exports a wiki page (or a hand-composed markdown body) to:
    pdf   — via Pandoc → LaTeX → PDF (requires pandoc + TeX on server)
    tex   — Pandoc LaTeX source
    docx  — Pandoc Word
    html  — standalone Pandoc HTML with KaTeX/MathJax

Inputs come from wiki/_bibliography/*.bib (Phase 9) — Pandoc resolves
`[@key]` citations against the same files the in-browser Citation.js
resolves, producing a DOI-quality bibliography.

Path validation uses the Phase 6 CodeQL-verified commonpath sanitizer
via wiki_store.read_page. Never shells out with user-controlled
strings — every Pandoc argument comes from a whitelist or is routed
through a temp file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


_ALLOWED_FORMATS = {
    "pdf": {"pandoc_to": "pdf", "ext": "pdf", "engine": "pdflatex"},
    "tex": {"pandoc_to": "latex", "ext": "tex", "engine": None},
    "docx": {"pandoc_to": "docx", "ext": "docx", "engine": None},
    "html": {"pandoc_to": "html5", "ext": "html", "engine": None},
}


schema = {
    "description": (
        "Export a wiki page through Pandoc. Produces PDF/LaTeX/DOCX/HTML "
        "with bibliography, figures, cross-refs, math. Phase 10."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "rel_path": {
                "type": "string",
                "description": "Wiki page path (e.g. 'specs/cortex/42-foo.md').",
            },
            "body": {
                "type": "string",
                "description": (
                    "Inline markdown body (use instead of rel_path for "
                    "ad-hoc exports). Frontmatter is honoured."
                ),
            },
            "format": {
                "type": "string",
                "enum": list(_ALLOWED_FORMATS.keys()),
                "default": "pdf",
            },
            "bibliography": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Override the page's frontmatter bibliography list. "
                    "Paths must be under _bibliography/."
                ),
            },
            "pandoc_args": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Extra Pandoc args. Validated against a whitelist of "
                    "safe flags (--toc, --number-sections, --template, …)."
                ),
            },
        },
    },
}


# Whitelisted Pandoc flags users can opt into. Anything not in here
# gets dropped silently — prevents subprocess injection via user input.
_SAFE_FLAG_ALLOWLIST = {
    "--toc",
    "--number-sections",
    "--standalone",
    "--section-divs",
    "--shift-heading-level-by=1",
    "--shift-heading-level-by=-1",
    "--citeproc",
    "--biblatex",
}


def _check_pandoc() -> str | None:
    """Return the pandoc binary path, or None if missing."""
    return shutil.which("pandoc")


def _filter_pandoc_args(args: list[str] | None) -> list[str]:
    if not args:
        return []
    return [a for a in args if a in _SAFE_FLAG_ALLOWLIST]


def _read_body(wiki_root: Path, rel_path: str | None, body: str | None) -> str:
    if body is not None:
        return body
    if not rel_path:
        raise ValueError("rel_path or body is required")
    from mcp_server.infrastructure.wiki_store import read_page

    content = read_page(wiki_root, rel_path)
    if content is None:
        raise FileNotFoundError(rel_path)
    return content


def _split_frontmatter(markdown: str) -> tuple[dict, str]:
    """Parse a best-effort frontmatter block out of ``markdown``.

    Returns (fields, body). Never raises; on any parse issue returns
    ({}, markdown). This is intentionally forgiving because the wiki
    writes titles with unquoted colons ("Decision: Use Postgres")
    that strict YAML parsers reject. We extract what we can, then
    feed only the body to pandoc and re-inject title/author/abstract
    as pandoc --metadata flags.
    """
    if not markdown.startswith("---"):
        return {}, markdown
    end = markdown.find("\n---", 3)
    if end < 0:
        return {}, markdown
    raw = markdown[3:end].strip("\n")
    body = markdown[end + 4 :].lstrip("\n")
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        # Match `key: value` with value running to end-of-line; values
        # can contain any character including further colons.
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        # Strip surrounding quotes if present; otherwise keep as-is.
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        fields[k] = v
    return fields, body


_META_KEYS_FOR_PANDOC = ("title", "subtitle", "author", "date", "abstract")


def _extract_bibliography_hint(markdown: str) -> list[str]:
    """Very small frontmatter reader — only looks for a bibliography:
    inline list. Full parsing lives in core/wiki_pages; this module
    only needs one field and avoids an extra import cycle.
    """
    if not markdown.startswith("---"):
        return []
    end = markdown.find("\n---", 3)
    if end < 0:
        return []
    fm = markdown[3:end]
    m = re.search(r"^\s*bibliography:\s*\[(.*?)\]", fm, re.MULTILINE)
    if not m:
        return []
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


def _resolve_bibliography_paths(wiki_root: Path, hints: list[str]) -> list[Path]:
    """Map relative bib paths to absolute files under wiki/_bibliography/.

    Rejects anything that escapes the _bibliography/ directory.
    """
    resolved: list[Path] = []
    bib_root = (wiki_root / "_bibliography").resolve()
    for hint in hints:
        # Allow both "foo.bib" and "_bibliography/foo.bib"
        if hint.startswith("_bibliography/"):
            rel = hint[len("_bibliography/") :]
        else:
            rel = hint
        if not rel.endswith(".bib") or "/" in rel.rstrip("/"):
            # Reject subpaths entirely — flat layout only.
            if "/" in rel or not rel.endswith(".bib"):
                continue
        target = (bib_root / rel).resolve()
        try:
            target.relative_to(bib_root)
        except ValueError:
            continue
        if target.is_file():
            resolved.append(target)
    return resolved


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    rel_path = args.get("rel_path") or None
    body_arg = args.get("body")
    fmt = args.get("format", "pdf")
    if fmt not in _ALLOWED_FORMATS:
        return {"error": f"unsupported format: {fmt!r}"}

    pandoc = _check_pandoc()
    if not pandoc:
        return {
            "error": (
                "pandoc is not installed — install it first and the "
                "four export formats (HTML, TEX, DOCX, PDF) will all "
                "work. Install: `brew install pandoc` (macOS) or "
                "`apt install pandoc` (Linux). "
                "For PDF specifically you ALSO need a LaTeX engine, "
                "but basictex / mactex / texlive-xetex are all "
                "acceptable — any one of them supplies `pdflatex`. "
                "basictex alone is enough for simple documents; "
                "missing packages can be added later with `tlmgr`."
            )
        }
    # Fast, actionable check specific to PDF — if pandoc is present
    # but no LaTeX engine is, the pandoc process would fail with a
    # noisy stderr. Pre-check and surface a clean message instead.
    if fmt == "pdf":
        engines = ("pdflatex", "xelatex", "lualatex", "tectonic")
        if not any(shutil.which(e) for e in engines):
            return {
                "error": (
                    "pandoc is installed but no LaTeX engine was found "
                    "on PATH (tried: " + ", ".join(engines) + "). "
                    "Install one: `brew install --cask basictex` "
                    "(smallest; includes pdflatex) or "
                    "`brew install --cask mactex-no-gui` (full) on "
                    "macOS; `apt install texlive-xetex` on Linux."
                )
            }

    from mcp_server.infrastructure.config import METHODOLOGY_DIR

    wiki_root = METHODOLOGY_DIR / "wiki"

    try:
        markdown = _read_body(wiki_root, rel_path, body_arg)
    except Exception as e:
        return {"error": f"cannot read source: {e}"}

    bib_hints = args.get("bibliography") or _extract_bibliography_hint(markdown)
    if not bib_hints:
        # Fall back to all bib files in _bibliography/
        bib_dir = wiki_root / "_bibliography"
        if bib_dir.exists():
            bib_hints = [p.name for p in bib_dir.glob("*.bib")]
    bib_files = _resolve_bibliography_paths(wiki_root, bib_hints)

    meta = _ALLOWED_FORMATS[fmt]

    # Strip the wiki's YAML frontmatter before handing to pandoc —
    # the wiki writes unquoted colons in titles ("Decision: Foo")
    # which pandoc's stricter YAML parser rejects. We re-inject the
    # interesting metadata fields through pandoc's --metadata flags
    # instead.
    fm, body_only = _split_frontmatter(markdown)

    with tempfile.TemporaryDirectory(prefix="cortex-export-") as tmpdir:
        tmp = Path(tmpdir)
        src = tmp / "page.md"
        src.write_text(body_only, encoding="utf-8")
        out = tmp / f"out.{meta['ext']}"

        cmd: list[str] = [pandoc, str(src), "-o", str(out)]
        # Explicit suppression of YAML metadata block parsing — the
        # source we write has no frontmatter, but be defensive.
        cmd.extend(["--from", "markdown-yaml_metadata_block"])
        cmd.extend(["--to", meta["pandoc_to"]])
        cmd.extend(["--standalone"])
        # Re-inject metadata from the stripped frontmatter.
        for key in _META_KEYS_FOR_PANDOC:
            if fm.get(key):
                cmd.extend(["--metadata", f"{key}={fm[key]}"])
        if bib_files:
            cmd.extend(["--citeproc"])
            for bf in bib_files:
                cmd.extend(["--bibliography", str(bf)])
        if meta["engine"]:
            cmd.extend([f"--pdf-engine={meta['engine']}"])
        cmd.extend(_filter_pandoc_args(args.get("pandoc_args")))

        try:
            completed = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
                env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
            )
        except subprocess.TimeoutExpired:
            return {"error": "pandoc timed out after 90s"}
        except Exception as e:
            return {"error": f"pandoc invocation failed: {e}"}

        if completed.returncode != 0:
            return {
                "error": "pandoc exited non-zero",
                "stderr": (completed.stderr or "")[:2000],
                "stdout": (completed.stdout or "")[:500],
            }
        if not out.exists():
            return {"error": "pandoc did not produce an output file"}

        data = out.read_bytes()
        return {
            "ok": True,
            "format": fmt,
            "bytes": len(data),
            "mime": {
                "pdf": "application/pdf",
                "tex": "application/x-tex",
                "docx": (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                "html": "text/html",
            }[fmt],
            "content_base64": _to_base64(data),
            "bibliography_used": [str(p.name) for p in bib_files],
        }


def _to_base64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")
