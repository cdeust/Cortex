"""Deterministic depth attributes for every Python function/class node.

node['depth'] = {
  signature:  "name(params) -> return" exactly as written (annotations kept),
  cyclomatic: McCabe complexity (1 + decision points: if/for/while/except/with,
              boolean operators, comprehensions' ifs, match cases, ternaries),
  raises:     exception names raised in the body,
  writes / reads: store tables the function's own SQL literals write / read,
  async:      whether it is a coroutine,
}
Source: the AST of the file at the graph's commit. McCabe 1976 (IEEE TSE SE-2(4)).
usage: python3 function_depth.py <repo> <graph>
"""

import ast
import json
import re
import sys

REPO, GP = sys.argv[1:3]
g = json.load(open(GP))
tables = {n["name"] for n in g["nodes"] if n["id"].startswith("table:store:")}
W = re.compile(
    r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?)\s+\"?(\w+)",
    re.I,
)
R = re.compile(r"(?:FROM|JOIN)\s+\"?(\w+)", re.I)


def cyclomatic(fn):
    c = 1
    for n in ast.walk(fn):
        if isinstance(
            n,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.ExceptHandler,
                ast.IfExp,
                ast.Assert,
            ),
        ):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += len(n.ifs)
        elif isinstance(n, getattr(ast, "match_case", ())):
            c += 1
    return c


def signature(fn):
    a = fn.args
    parts = [
        ast.unparse(x)
        if False
        else (x.arg + (": " + ast.unparse(x.annotation) if x.annotation else ""))
        for x in a.posonlyargs + a.args
    ]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts += [
        x.arg + (": " + ast.unparse(x.annotation) if x.annotation else "")
        for x in a.kwonlyargs
    ]
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    ret = " -> " + ast.unparse(fn.returns) if fn.returns is not None else ""
    return f"{fn.name}({', '.join(parts)}){ret}"


def sql_effects(fn):
    w, r = set(), set()
    for n in ast.walk(fn):
        if (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", n.value, re.I)
        ):
            w |= {t.lower() for t in W.findall(n.value) if t.lower() in tables}
            r |= {t.lower() for t in R.findall(n.value) if t.lower() in tables}
    return sorted(w), sorted(r)


def raises(fn):
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Raise) and n.exc is not None:
            e = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
            out.add(ast.unparse(e))
    return sorted(out)


trees, done = {}, 0
for n in g["nodes"]:
    if n["type"] not in ("function", "class") or not n["filePath"].endswith(".py"):
        continue
    p = n["filePath"]
    if p not in trees:
        try:
            trees[p] = ast.parse(open(f"{REPO}/{p}", encoding="utf-8").read())
        except (OSError, SyntaxError, UnicodeDecodeError):
            trees[p] = None
    t = trees[p]
    if t is None:
        continue
    lr = n.get("lineRange") or [0, 0]
    kinds = (
        (ast.ClassDef,)
        if n["type"] == "class"
        else (ast.FunctionDef, ast.AsyncFunctionDef)
    )
    cand = sorted(
        (x for x in ast.walk(t) if isinstance(x, kinds) and x.name == n["name"]),
        key=lambda x: abs(x.lineno - lr[0]),
    )
    if not cand:
        continue
    x = cand[0]
    if n["type"] == "class":
        n["depth"] = {
            "bases": [ast.unparse(b) for b in x.bases],
            "methods": [
                b.name
                for b in x.body
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
            ],
        }
    else:
        w, r = sql_effects(x)
        n["depth"] = {
            "signature": signature(x),
            "cyclomatic": cyclomatic(x),
            "raises": raises(x),
            "writes": w,
            "reads": r,
            "async": isinstance(x, ast.AsyncFunctionDef),
        }
    done += 1
json.dump(g, open(GP, "w"), indent=2, ensure_ascii=False)
print("nodes given depth attributes:", done)
