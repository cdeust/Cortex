"""Measured coverage of the knowledge graph, per category, against deterministic ground
truth (AST / filesystem)."""

import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# source: how many missing examples a report lists per area (readability)
MAX_EXAMPLES = 3

root = Path(sys.argv[1])
g = json.load(open(sys.argv[2]))
ids = {n["id"] for n in g["nodes"]}
byid = {n["id"]: n for n in g["nodes"]}
out = defaultdict(set)
inn = defaultdict(set)
etype = Counter(e["type"] for e in g["edges"])
for e in g["edges"]:
    out[e["source"]].add(e["type"])
    inn[e["target"]].add(e["type"])
scan = json.load(open(root / ".ua/intermediate/scan-result.json"))["files"]
cat = {f["path"]: f["fileCategory"] for f in scan}
fid = {}
for n in g["nodes"]:
    if (
        n.get("filePath")
        and n["type"] not in ("function", "class")
        and n["filePath"] not in fid
    ):
        fid[n["filePath"]] = n["id"]
R = {}
# 1. file nodes per category
c = Counter(cat.values())
has = Counter(cat[p] for p in cat if p in fid)
R["file_nodes"] = {k: f"{has[k]}/{c[k]}" for k in c}
# 2. symbols: AST top-level defs + methods vs graph nodes (python, project code)
tot = Counter()
got = Counter()
miss_examples = defaultdict(list)
for p in cat:
    if not p.endswith(".py"):
        continue
    area = (
        "tests"
        if p.startswith(("tests_py/", "fuzz/"))
        else ("benchmarks" if p.startswith("benchmarks/") else "prod")
    )
    try:
        t = ast.parse((root / p).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        continue
    syms = []
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            syms.append(("function", n.name))
        elif isinstance(n, ast.ClassDef):
            syms.append(("class", n.name))
            syms += [
                ("function", m.name)
                for m in n.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
    for kind, name in syms:
        tot[area] += 1
        if (
            f"function:{p}:{name}" in ids
            or f"class:{p}:{name}" in ids
            or f"function:{p}:{kind}" in ids
        ):
            got[area] += 1
        elif len(miss_examples[area]) < MAX_EXAMPLES:
            miss_examples[area].append(f"{p}:{name}")
R["python_symbols"] = {
    a: f"{got[a]}/{tot[a]} ({100 * got[a] / max(tot[a], 1):.0f}%)" for a in tot
}
R["python_symbols_missing_examples"] = dict(miss_examples)
# 3. tests linked to production
tests = [
    p
    for p in cat
    if p.startswith("tests_py/")
    and p.endswith(".py")
    and Path(p).name.startswith("test_")
]
lt = sum(1 for p in tests if "tested_by" in inn.get(fid.get(p, ""), set()))
R["test_files_linked_by_tested_by"] = (
    f"{lt}/{len(tests)} ({100 * lt / len(tests):.0f}%)"
)
prod = [
    p
    for p in cat
    if p.startswith(("mcp_server/", "scripts/"))
    and p.endswith(".py")
    and not p.endswith("__init__.py")
]
lp = sum(
    1
    for p in prod
    if "tested_by" in out.get(fid.get(p, ""), set())
    or "tested" in byid.get(fid.get(p, ""), {}).get("tags", [])
)
R["prod_files_with_tests"] = f"{lp}/{len(prod)} ({100 * lp / len(prod):.0f}%)"
# 4. docs linked to something
docs = [p for p in cat if cat[p] == "docs"]
ld = sum(1 for p in docs if out.get(fid.get(p, ""), set()) & {"documents", "related"})
R["docs_with_outgoing_link"] = f"{ld}/{len(docs)} ({100 * ld / len(docs):.0f}%)"
# 5. config/infra/script/data with any edge
for k in ("config", "infra", "script", "data"):
    ps = [p for p in cat if cat[p] == k]
    linked = sum(1 for p in ps if out.get(fid.get(p, "")) or inn.get(fid.get(p, "")))
    R[f"{k}_with_any_edge"] = (
        f"{linked}/{len(ps)} ({100 * linked / max(len(ps), 1):.0f}%)"
    )
orph = [n["id"] for n in g["nodes"] if not out.get(n["id"]) and not inn.get(n["id"])]
R["orphan_nodes"] = len(orph)
R["edge_types"] = dict(etype)
print(json.dumps(R, indent=1))
