"""`documents` edges ADR page -> code module, from `ADR-NNNN` citations in the code.

Every `ADR-NNNN` token in a Python file (docstrings, `# source:` comments) is resolved
through wiki/manifest.json (`pages[ADR-NNNN].path`, the canonical wiki page) to the
page's document node; edge evidence = file:line of the citation.
usage: python3 link_adr_citations.py <repo> <graph>
"""

import json
import re
import subprocess
import sys

REPO, GP = sys.argv[1:3]
pages = json.load(open(f"{REPO}/wiki/manifest.json"))["pages"]
g = json.load(open(GP))
by_path = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n["type"] not in ("function", "class", "table")
}
have = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
rx = re.compile(r"\bADR-(\d{4})\b")
added = unresolved = 0
for p in subprocess.run(
    ["git", "-C", REPO, "ls-files", "*.py"], capture_output=True, text=True
).stdout.split():
    if p not in by_path:
        continue
    seen = set()
    for ln, line in enumerate(
        open(f"{REPO}/{p}", encoding="utf-8", errors="ignore"), 1
    ):
        for num in rx.findall(line):
            key = f"ADR-{num}"
            if key in seen:
                continue
            seen.add(key)
            page = pages.get(key)
            src = by_path.get(f"wiki/{page['path']}") if page else None
            if not src:
                unresolved += 1
                continue
            if (src, by_path[p], "documents") in have:
                continue
            g["edges"].append(
                {
                    "source": src,
                    "target": by_path[p],
                    "type": "documents",
                    "direction": "forward",
                    "weight": 0.9,
                    "evidence": f"{p}:{ln} cites {key}",
                }
            )
            have.add((src, by_path[p], "documents"))
            added += 1
json.dump(g, open(GP, "w"), indent=2, ensure_ascii=False)
print(
    "documents edges added:",
    added,
    "| citations to an ADR absent from the manifest/graph:",
    unresolved,
)
