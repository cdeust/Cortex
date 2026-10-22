"""Fill short node summaries (< 60 chars) from the author's own docstring.

For function/class/file nodes of Python files whose summary is shorter than 60
characters, the first paragraph of the matching docstring (module docstring for a
file node) replaces it when that paragraph is longer. Provenance is recorded in
node['summarySource'] = 'docstring'. Nothing is invented: a node without a usable
docstring keeps its summary (for the LLM pass).
usage: python3 summaries_from_docstrings.py <repo> <graph>
"""

import ast
import json
import re
import sys

# source: cap so a summary stays a paragraph, not the whole docstring
MAX_SUMMARY_CHARS = 400
# source: same "real summary" floor as scorecard.py
MIN_PARAGRAPH_CHARS = 25

REPO, GP = sys.argv[1:3]
# source: legacy length proxy (see .ua/README.md: replaced by fn_depth)
MIN = 60
g = json.load(open(GP))


def first_paragraph(doc):
    if not doc:
        return ""
    para = re.split(r"\n\s*\n", doc.strip(), maxsplit=1)[0]
    para = re.sub(r"\s+", " ", para).strip()
    return (
        para[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"
        if len(para) > MAX_SUMMARY_CHARS
        else para
    )


trees = {}


def tree(p):
    if p not in trees:
        try:
            trees[p] = ast.parse(open(f"{REPO}/{p}", encoding="utf-8").read())
        except (OSError, SyntaxError, UnicodeDecodeError):
            trees[p] = None
    return trees[p]


updated = considered = 0
for n in g["nodes"]:
    if n["type"] not in ("function", "class", "file") or not n["filePath"].endswith(
        ".py"
    ):
        continue
    if len(n.get("summary", "")) >= MIN:
        continue
    considered += 1
    t = tree(n["filePath"])
    if t is None:
        continue
    if n["type"] == "file":
        doc = ast.get_docstring(t)
    else:
        lr = n.get("lineRange") or [0, 0]
        cand = [
            x
            for x in ast.walk(t)
            if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and x.name == n["name"]
        ]
        cand.sort(key=lambda x: abs(x.lineno - lr[0]))
        doc = ast.get_docstring(cand[0]) if cand else None
    para = first_paragraph(doc)
    if len(para) > len(n.get("summary", "")) and len(para) >= MIN_PARAGRAPH_CHARS:
        n["summary"] = para
        n["summarySource"] = "docstring"
        updated += 1
json.dump(g, open(GP, "w"), indent=2, ensure_ascii=False)
print(
    "short summaries:",
    considered,
    "| replaced by the docstring's first paragraph:",
    updated,
)
