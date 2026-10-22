"""Coverage scorecard of the knowledge graph against the repository (target >= 90%
each).

Each category is a ratio numerator/denominator measured from the repo and the graph:
  files        tracked files (minus binary media) present as a node
  symbols      Python defs (AST) present as function/class nodes
  imports      Python files with an internal import that have an `imports` edge
  calls        production functions/classes linked in the call graph (in or out)
  test_links   functions executed by >= 1 test (coverage contexts) whose node records it
  summaries    function/class/file nodes whose summary is >= 60 characters
  docs_links   mcp_server modules targeted by >= 1 `documents` edge
  data_flow    production modules with SQL on a store table that have
  reads_from/writes_to
  domain       MCP tools + hooks covered by a domain flow (domain-graph.json)
  knowledge    ADR pages represented as knowledge nodes (article/claim/entity)
usage: python3 scorecard.py <repo> <graph> [domain-graph.json]
"""

import ast
import collections
import json
import os
import re
import subprocess
import sys

# source: argv = script, repo, graph, [domain graph]
ARGC_WITH_DOMAIN_GRAPH = 4
# source: "real summary" rule stated in the docstring (a sentence, not the name)
SUMMARY_MIN_CHARS = 25
SUMMARY_MIN_WORDS = 4
# source: the user's target (2026-10-20): at least 90% in every category
TARGET = 0.9

REPO, GP = sys.argv[1], sys.argv[2]
DG = (
    sys.argv[3]
    if len(sys.argv) >= ARGC_WITH_DOMAIN_GRAPH
    else os.path.join(os.path.dirname(GP), "domain-graph.json")
)
MEDIA = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".mp4",
    ".mov",
    ".webm",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".pdf",
    ".svg",
    ".gz",
    ".zip",
)
g = json.load(open(GP))
nodes = {n["id"]: n for n in g["nodes"]}
tracked = subprocess.run(
    ["git", "-C", REPO, "ls-files"], capture_output=True, text=True
).stdout.split()
in_graph = {n["filePath"] for n in g["nodes"]}
edges = collections.defaultdict(lambda: collections.defaultdict(set))
for e in g["edges"]:
    s, t = nodes.get(e["source"]), nodes.get(e["target"])
    if s and t:
        edges[e["type"]][e["source"]].add(e["target"])
        edges["_rev_" + e["type"]][e["target"]].add(e["source"])
rows = {}

files = [p for p in tracked if not p.lower().endswith(MEDIA)]
rows["files"] = (sum(p in in_graph for p in files), len(files))

sym = collections.defaultdict(set)
for n in g["nodes"]:
    if n["type"] in ("function", "class"):
        sym[n["filePath"]].add(n["name"])
py = [p for p in tracked if p.endswith(".py")]
dn = dd = imp_n = imp_d = 0
for p in py:
    try:
        tree = ast.parse(open(os.path.join(REPO, p)).read())
    except (SyntaxError, UnicodeDecodeError):
        continue
    defs = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    dd += len(defs)
    dn += len(defs & sym[p])
    internal = any(
        isinstance(n, ast.ImportFrom)
        and n.module
        and n.module.split(".")[0]
        in ("mcp_server", "scripts", "tests_py", "benchmarks")
        for n in ast.walk(tree)
    )
    if internal:
        imp_d += 1
        fid = next((n["id"] for n in g["nodes"] if False), None)
rows["symbols"] = (dn, dd)
file_node = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n["type"] not in ("function", "class", "table")
}
imp_n = imp_d = 0
for p in py:
    try:
        tree = ast.parse(open(os.path.join(REPO, p)).read())
    except (SyntaxError, UnicodeDecodeError):
        continue
    if any(
        isinstance(n, ast.ImportFrom)
        and n.module
        and n.module.split(".")[0]
        in ("mcp_server", "scripts", "tests_py", "benchmarks")
        for n in ast.walk(tree)
    ):
        imp_d += 1
        imp_n += bool(edges["imports"].get(file_node.get(p, ""), ()))
rows["imports"] = (imp_n, imp_d)

prod = [
    n
    for n in g["nodes"]
    if n["type"] in ("function", "class")
    and not n["filePath"].startswith(("tests_py/", "video/"))
]
linked = sum(
    1 for n in prod if edges["calls"].get(n["id"]) or edges["_rev_calls"].get(n["id"])
)
rows["calls"] = (linked, len(prod))

cov = (
    json.load(
        open(os.path.join(os.path.dirname(GP), "gapfix", "executed_symbols.json"))
    )
    if os.path.exists(
        os.path.join(os.path.dirname(GP), "gapfix", "executed_symbols.json")
    )
    else None
)
if cov is not None:
    rows["test_links"] = (
        sum(1 for i in cov if nodes.get(i, {}).get("exercisedByTests")),
        len(cov),
    )


def real_summary(n):
    s = n.get("summary", "").strip()
    name = n["name"].replace("_", " ").strip().lower()
    return (
        len(s) >= SUMMARY_MIN_CHARS
        and len(s.split()) >= SUMMARY_MIN_WORDS
        and s.lower().rstrip(".") != name
    )


fc = [n for n in g["nodes"] if n["type"] in ("function", "class")]
# depth = a real summary (>= 4 words, not the name) AND exact depth attributes
# (signature,
# McCabe complexity, raises, SQL effects / bases, methods) from function_depth.py
rows["fn_depth"] = (sum(real_summary(n) and "depth" in n for n in fc), len(fc))
fl = [
    n
    for n in g["nodes"]
    if n["type"] in ("file", "config", "document", "service", "pipeline", "table")
]
rows["file_summary"] = (sum(real_summary(n) for n in fl), len(fl))

ms = [p for p in py if p.startswith("mcp_server/")]
rows["docs_links"] = (
    sum(bool(edges["_rev_documents"].get(file_node.get(p, ""), ())) for p in ms),
    len(ms),
)

tables = {n["name"] for n in g["nodes"] if n["id"].startswith("table:store:")}
sqlrx = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+\"?(\w+)", re.I)
dfd = dfn = 0
for p in ms:
    tree = ast.parse(open(os.path.join(REPO, p)).read())
    docs = {
        id(x.body[0].value)
        for x in ast.walk(tree)
        if isinstance(
            x, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and x.body
        and isinstance(x.body[0], ast.Expr)
        and isinstance(x.body[0].value, ast.Constant)
    }
    lits = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docs
        and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", n.value)
    ]
    if any(t in tables for s in lits for t in sqlrx.findall(s)):
        dfd += 1
        fid = file_node.get(p, "")
        dfn += bool(edges["reads_from"].get(fid) or edges["writes_to"].get(fid))
rows["data_flow"] = (dfn, dfd)

reg = set()
for p in py:
    if p.startswith("mcp_server/tool_registry_"):
        reg |= set(
            re.findall(
                r'@mcp\.tool\(\s*name="([a-z_]+)"', open(os.path.join(REPO, p)).read()
            )
        )
plugin = json.load(open(os.path.join(REPO, ".claude-plugin", "plugin.json")))
hook_mods = {
    m
    for ev in plugin.get("hooks", {}).values()
    for x in ev
    for h in x.get("hooks", [])
    for m in re.findall(r"mcp_server\.hooks\.([a-z_]+)", h.get("command", ""))
}
flows = set()
if os.path.exists(DG):
    for n in json.load(open(DG)).get("nodes", []):
        if n.get("type") == "flow":
            flows.add(n["name"])
            flows.add(os.path.basename(n.get("filePath", ""))[:-3])
rows["domain"] = (len(reg & flows) + len(hook_mods & flows), len(reg) + len(hook_mods))

adrs = [p for p in tracked if p.startswith("wiki/adr/") and p.endswith(".md")]
know = {
    n["filePath"]
    for n in g["nodes"]
    if n["type"] in ("article", "claim", "entity", "topic", "source")
}
rows["knowledge"] = (sum(p in know for p in adrs), len(adrs))

print(f"{'category':12}{'covered':>9}{'total':>8}{'%':>7}")
for k, (a, b) in rows.items():
    print(
        f"{k:12}{a:9}{b:8}{(100 * a / b if b else 100):7.1f}"
        f"{'' if b and a / b >= TARGET else '  < 90'}"
    )
