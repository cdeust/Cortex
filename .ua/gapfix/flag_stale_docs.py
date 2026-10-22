"""Deterministic gap-fix: flag wiki/docs pages whose `source:` frontmatter names a file
absent from the tree."""

import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
gp = Path(sys.argv[2])
g = json.loads(gp.read_text())
byid = {n["id"]: n for n in g["nodes"]}
stale = []
for md in sorted((root / "wiki").rglob("*.md")) + sorted((root / "docs").rglob("*.md")):
    text = md.read_text(encoding="utf-8", errors="replace")
    head = text.splitlines()[:40]
    status = next((ln for ln in head if re.match(r"\s*status:", ln, re.I)), "")
    superseded = bool(re.search(r"supersed|deprecat|retired|withdrawn", status, re.I))
    for i, line in enumerate(head, start=1):
        m = re.match(r"\s*source:\s*[`'\"]?([^`'\"#\s;]+)", line, re.I)
        if not m:
            continue
        ref = m.group(1)
        if (
            "/" not in ref
            or ref.startswith(("http", "ADR", "issue", "#"))
            or "." not in ref.rsplit("/", 1)[-1]
        ):
            continue
        if not (root / ref).exists():
            rel = md.relative_to(root).as_posix()
            stale.append(
                {
                    "doc": rel,
                    "line": i,
                    "missing": ref,
                    "superseded": superseded,
                    "status": status.strip()[:120],
                }
            )
            n = byid.get(f"document:{rel}")
            if n is not None and not superseded:
                tags = n.setdefault("tags", [])
                if "stale-source" not in tags:
                    tags.append("stale-source")
                n["staleSource"] = {"missing": ref, "evidence": f"{rel}:{i}"}
gp.write_text(json.dumps(g))
json.dump(stale, open(gp.parent / "gapfix" / "stale_sources.json", "w"), indent=1)
live = [x for x in stale if not x["superseded"]]
print(len(stale), "missing-source refs;", len(live), "on non-superseded docs")
for x in live:
    print(f"  STALE {x['doc']}:{x['line']} -> {x['missing']} | {x['status']}")
