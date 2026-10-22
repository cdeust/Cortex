"""Deterministic data-flow edges from SQL string literals in Python code.

CREATE TABLE -> table nodes + defines_schema; INSERT/UPDATE/DELETE/MERGE/UPSERT
targets -> writes_to; FROM/JOIN targets -> reads_from. Only identifiers that
are tables created somewhere in the scanned code count, so CTE names, columns
and Python words never become edges. Evidence = file:line of the literal.
"""

import ast
import json
import re
import subprocess
import collections
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
G = ROOT + "/.ua/knowledge-graph.json"
IDENT = r'(?:"?[A-Za-z_][A-Za-z0-9_]*"?\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?'
CREATE = re.compile(
    r"CREATE\s+(?:UNLOGGED\s+|TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    + IDENT,
    re.I,
)
CREATE_V = re.compile(
    r"CREATE\s+(?:VIRTUAL\s+TABLE|(?:MATERIALIZED\s+)?VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    + IDENT,
    re.I,
)
WRITE = re.compile(
    r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|COPY)\s+"
    + IDENT,
    re.I,
)
READ = re.compile(r"(?:FROM|JOIN)\s+" + IDENT, re.I)
SQLISH = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|COPY|TRUNCATE)\b", re.I)


def literals(tree):
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and SQLISH.search(n.value)
        ):
            yield n.lineno, n.value
        elif isinstance(n, ast.JoinedStr):
            s = "".join(
                v.value if isinstance(v, ast.Constant) else " X " for v in n.values
            )
            if SQLISH.search(s):
                yield n.lineno, s


files = [
    p
    for p in subprocess.run(
        ["git", "-C", ROOT, "ls-files", "*.py"], capture_output=True, text=True
    ).stdout.split()
    if p.startswith(("mcp_server/", "scripts/"))
]
parsed = {}
for p in files:
    try:
        parsed[p] = list(literals(ast.parse(open(f"{ROOT}/{p}").read())))
    except SyntaxError:
        pass
defs = collections.defaultdict(list)  # table -> [(file,line)]
for p, lits in parsed.items():
    for ln, s in lits:
        for rx in (CREATE, CREATE_V):
            for m in rx.finditer(s):
                defs[m.group(1).lower()].append((p, ln))
tables = set(defs)
reads, writes = collections.defaultdict(dict), collections.defaultdict(dict)
for p, lits in parsed.items():
    for ln, s in lits:
        for m in WRITE.finditer(s):
            t = m.group(1).lower()
            if t in tables:
                writes[p].setdefault(t, ln)
        for m in READ.finditer(s):
            t = m.group(1).lower()
            if t in tables:
                reads[p].setdefault(t, ln)

g = json.load(open(G))
ids = {n["id"] for n in g["nodes"]}
filenode = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n["type"] not in ("function", "class", "table")
}
added_nodes = added_edges = 0
for t, where in sorted(defs.items()):
    tid = f"table:store:{t}"
    if tid not in ids:
        first = where[0]
        g["nodes"].append(
            {
                "id": tid,
                "type": "table",
                "name": t,
                "filePath": first[0],
                "lineRange": [first[1], first[1]],
                "summary": (
                    f"Store table `{t}`, created in SQL inside "
                    f"{', '.join(sorted({w[0] for w in where}))}."
                ),
                "tags": ["table", "store", "sql"],
                "complexity": "simple",
                "provenance": (
                    "gapfix:link_sql_dataflow (CREATE TABLE in a Python string literal)"
                ),
            }
        )
        ids.add(tid)
        added_nodes += 1
    for f, ln in where:
        if f in filenode:
            g["edges"].append(
                {
                    "source": filenode[f],
                    "target": tid,
                    "type": "defines_schema",
                    "direction": "forward",
                    "weight": 1.0,
                    "evidence": f"{f}:{ln} CREATE TABLE",
                }
            )
            added_edges += 1
for kind, src in (("writes_to", writes), ("reads_from", reads)):
    for f, ts in src.items():
        if f not in filenode:
            continue
        for t, ln in ts.items():
            g["edges"].append(
                {
                    "source": filenode[f],
                    "target": f"table:store:{t}",
                    "type": kind,
                    "direction": "forward",
                    "weight": 0.8,
                    "evidence": f"{f}:{ln} SQL literal",
                }
            )
            added_edges += 1
# dedupe edges
seen = set()
out = []
for e in g["edges"]:
    k = (e["source"], e["target"], e["type"])
    if k in seen:
        continue
    seen.add(k)
    out.append(e)
g["edges"] = out
json.dump(g, open(G, "w"), indent=2, ensure_ascii=False)
print(
    "tables",
    len(tables),
    "new table nodes",
    added_nodes,
    "edges added",
    added_edges,
    "files writing",
    len(writes),
    "files reading",
    len(reads),
)
print(sorted(tables))
