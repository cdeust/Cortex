"""Name resolution for link_calls_resolved.py: modules, imports, classes, types.

The rules are listed in link_calls_resolved.py's docstring. `configure(root)` sets
the repository root every path is relative to; parsed modules are cached.
"""

import ast
from pathlib import Path

# source: bound on followed re-exports / base classes; a project chain deeper
# than this was not observed in Cortex (cycle guard, not a tuned value)
MAX_DEPTH = 6

ROOT = Path(".")


def configure(root):
    """Set the repository root (a Path) for every later resolution."""
    global ROOT
    ROOT = root


def mod_path(mod):
    p = ROOT / Path(*mod.split("."))
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py").relative_to(ROOT).as_posix()
    if (p / "__init__.py").is_file():
        return (p / "__init__.py").relative_to(ROOT).as_posix()
    return None


def mod_name(path):
    parts = path[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


class Module:
    def __init__(self, path, tree):
        self.path, self.tree, self.name = path, tree, mod_name(path)
        self.pkg = (
            self.name if path.endswith("__init__.py") else self.name.rpartition(".")[0]
        )
        self.defs, self.classes, self.imports = {}, {}, {}
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defs[n.name] = n
            elif isinstance(n, ast.ClassDef):
                self.defs[n.name] = n
                self.classes[n.name] = n
        self.imports = import_table(tree.body, self.pkg, top=True)


def import_table(stmts, pkg, top=False):
    table = {}
    walker = stmts if top else [s for st in stmts for s in ast.walk(st)]
    for n in walker:
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level:
                base = pkg.split(".") if pkg else []
                base = base[: len(base) - (n.level - 1)] if n.level > 1 else base
                mod = ".".join(base + ([mod] if mod else []))
            for a in n.names:
                if a.name == "*":
                    continue
                sub = mod_path(f"{mod}.{a.name}") if mod else None
                table[a.asname or a.name] = (
                    ("module", sub) if sub else ("symbol", mod, a.name)
                )
        elif isinstance(n, ast.Import):
            for a in n.names:
                p = mod_path(a.name)
                if p:
                    table[a.asname or a.name.split(".")[0]] = (
                        "module",
                        p if a.asname else mod_path(a.name.split(".")[0]) or p,
                    )
    return table


MODS = {}


def load(path):
    if path in MODS:
        return MODS[path]
    try:
        MODS[path] = Module(path, ast.parse((ROOT / path).read_text(encoding="utf-8")))
    except (SyntaxError, OSError, UnicodeDecodeError):
        MODS[path] = None
    return MODS[path]


def resolve_symbol(path, name, depth=0):
    """(path, name, node) where `name` is defined, following imports/re-exports."""
    m = load(path) if path else None
    if not m or depth > MAX_DEPTH:
        return None
    if name in m.defs:
        return (path, name, m.defs[name])
    imp = m.imports.get(name)
    if imp and imp[0] == "symbol":
        p = mod_path(imp[1]) if imp[1] else None
        return resolve_symbol(p, imp[2], depth + 1) if p else None
    return None


def resolve_ref(m, local_imports, name):
    if name in m.defs:
        return (m.path, name, m.defs[name])
    imp = local_imports.get(name) or m.imports.get(name)
    if imp and imp[0] == "symbol":
        p = mod_path(imp[1]) if imp[1] else None
        return resolve_symbol(p, imp[2]) if p else None
    return None


def module_of(m, local_imports, name):
    imp = local_imports.get(name) or m.imports.get(name)
    return imp[1] if imp and imp[0] == "module" else None


def class_bases(cpath, cnode):
    m = load(cpath)
    out = []
    for b in cnode.bases:
        r = None
        if isinstance(b, ast.Name):
            r = resolve_ref(m, {}, b.id)
        elif isinstance(b, ast.Attribute) and isinstance(b.value, ast.Name):
            mp = module_of(m, {}, b.value.id)
            r = resolve_symbol(mp, b.attr) if mp else None
        if r and isinstance(r[2], ast.ClassDef):
            out.append(r)
    return out


def find_method(cls, meth, depth=0, include_self=True):
    cpath, cname, cnode = cls
    if include_self:
        for n in cnode.body:
            if (
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == meth
            ):
                return (cpath, meth)
    if depth > MAX_DEPTH:
        return None
    for b in class_bases(cpath, cnode):
        r = find_method(b, meth, depth + 1)
        if r:
            return r
    return None
