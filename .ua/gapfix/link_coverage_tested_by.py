"""Cycle 2: tested_by edges measured by coverage.py dynamic contexts (pytest --cov-
context=test).

Ground truth = lines executed while a given test ran. To exclude import-time noise
(module-level lines run
by whichever test first imports a module), a link counts only lines strictly inside a
function/method body
(AST ranges recomputed from source, not taken from the graph).
  - file level:     prod file  -> test file   (>=1 body line executed by a test of that
  file)
  - symbol level:   no edge (a shared helper would link to hundreds of tests); the node
  gets
                    `exercisedByTests` (number of test files executing >=1 body line)
                    and tag `tested`
Evidence: "coverage: <n> body lines executed by <test nodeid>". Edges already present
are not duplicated.
Usage: link_coverage_tested_by.py <repo_root> <.coverage> <graph.json>
"""

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from coverage import CoverageData

root = Path(sys.argv[1])
data = CoverageData(basename=sys.argv[2])
data.read()
gp = Path(sys.argv[3])
g = json.loads(gp.read_text())
ids = {n["id"] for n in g["nodes"]}
fid = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n.get("filePath") and n["type"] not in ("function", "class")
}
have = {(e["source"], e["target"], e["type"]) for e in g["edges"]}


def body_ranges(path):
    """[(node_id, first_body_line, end_line)] for every function/method, innermost-first
    resolution."""
    try:
        t = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return []
    rel = path.relative_to(root).as_posix()
    out = []
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            start = n.body[0].lineno
            if (
                isinstance(n.body[0], ast.Expr)
                and isinstance(getattr(n.body[0], "value", None), ast.Constant)
                and len(n.body) > 1
            ):
                start = n.body[1].lineno  # skip docstring
            out.append((f"function:{rel}:{n.name}", start, n.end_lineno))
    return sorted(out, key=lambda r: r[2] - r[1])  # smallest span first = innermost


def test_file(ctx):
    f = ctx.split("::", 1)[0]
    return f if f.endswith(".py") and f"{f}" in fid else None


file_hits = defaultdict(lambda: defaultdict(int))
sym_hits = defaultdict(lambda: defaultdict(int))
ex = {}
for measured in data.measured_files():
    p = Path(measured)
    try:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        # worktree path -> repo-relative
        s = str(p)
        i = s.find("/mcp_server/") if "/mcp_server/" in s else s.find("/scripts/")
        if i < 0:
            continue
        rel = s[i + 1 :]
    if rel not in fid or rel.startswith("tests_py/"):
        continue
    ranges = body_ranges(root / rel)
    for line, ctxs in (data.contexts_by_lineno(measured) or {}).items():
        owner = next((r for r in ranges if r[1] <= line <= r[2]), None)
        if not owner:
            continue  # module-level line: import-time noise
        for c in ctxs:
            t = test_file(c.split("|")[0]) if c else None
            if not t:
                continue
            file_hits[rel][t] += 1
            ex.setdefault((rel, t), c.split("|")[0])
            if owner[0] in ids:
                sym_hits[owner[0]][t] += 1
                ex.setdefault((owner[0], t), c.split("|")[0])

added = []


def link(src, tfile, n, key):
    k = (src, fid[tfile], "tested_by")
    if k in have:
        return
    have.add(k)
    added.append(
        {
            "source": src,
            "target": fid[tfile],
            "type": "tested_by",
            "direction": "forward",
            "weight": 0.6,
            "evidence": f"coverage: {n} body lines executed by {ex[key]}",
            "provenance": (
                "gapfix/link_coverage_tested_by.py (pytest --cov-context=test)"
            ),
        }
    )


for rel, ts in file_hits.items():
    for t, n in ts.items():
        link(fid[rel], t, n, (rel, t))
byid = {nd["id"]: nd for nd in g["nodes"]}
for sid, ts in sym_hits.items():
    byid[sid]["exercisedByTests"] = len(ts)
src = {e["source"] for e in added} | set(sym_hits)
for nd in g["nodes"]:
    if nd["id"] in src and "tested" not in nd.setdefault("tags", []):
        nd["tags"].append("tested")
g["edges"] += added
gp.write_text(json.dumps(g))
json.dump(
    added, open(gp.parent / "gapfix" / "added_coverage_tested_by.json", "w"), indent=1
)
print(
    f"files measured {len(file_hits)}; symbols measured {len(sym_hits)}; "
    f"added {len(added)} tested_by edges "
    f"({sum(1 for e in added if not e['source'].startswith('function:'))} file-level)"
)
