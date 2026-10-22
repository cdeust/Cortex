"""Call targets for link_calls_resolved.py: which node a call resolves to.

Types of locals (annotations, constructors, factories annotated `-> C`), mixin
composition, callables passed as references, and the per-call resolution itself;
module, import and class lookups come from call_resolution.py.
"""

import ast

from call_resolution import (
    class_bases,
    find_method,
    load,
    module_of,
    resolve_ref,
    resolve_symbol,
)


def ann_class(m, local_imports, ann):
    if ann is None:
        return None
    if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
        try:
            ann = ast.parse(ann.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(ann, ast.BinOp):  # C | None
        return ann_class(m, local_imports, ann.left) or ann_class(
            m, local_imports, ann.right
        )
    if isinstance(ann, ast.Subscript):  # Optional[C]
        return ann_class(m, local_imports, ann.slice)
    if isinstance(ann, ast.Name):
        r = resolve_ref(m, local_imports, ann.id)
    elif isinstance(ann, ast.Attribute) and isinstance(ann.value, ast.Name):
        mp = module_of(m, local_imports, ann.value.id)
        r = resolve_symbol(mp, ann.attr) if mp else None
    else:
        return None
    return r if r and isinstance(r[2], ast.ClassDef) else None


def _kind(r):
    return "class" if isinstance(r[2], ast.ClassDef) else "function"


def _name_targets(m, local_imports, name):
    """`f(...)`: the resolved def or class (and the class's `__init__`)."""
    r = resolve_ref(m, local_imports, name)
    if not r:
        return []
    out = [(_kind(r), r[0], r[1])]
    if isinstance(r[2], ast.ClassDef):
        init = find_method(r, "__init__")
        if init:
            out.append(("function", init[0], "__init__"))
    return out


def _receiver_class(m, cls, base, meth, local_imports, types):
    """(class the receiver `base` is known to be, or None; module-level result).

    The second item is set when `base` is an imported module: then the call is
    resolved as `module.meth` and no class lookup applies.
    """
    if base.id in ("self", "cls") and cls:
        return cls, None
    if base.id in types:
        return types[base.id], None
    mp = module_of(m, local_imports, base.id)
    if mp:
        r = resolve_symbol(mp, meth)
        return None, ([(_kind(r), r[0], r[1])] if r else [])
    r = resolve_ref(m, local_imports, base.id)
    return (r if r and isinstance(r[2], ast.ClassDef) else None), None


def _attribute_targets(m, cls, f, local_imports, types):
    """`x.m(...)` / `super().m(...)`: the method m of the receiver's class."""
    base, meth = f.value, f.attr
    target_cls = None
    if isinstance(base, ast.Name):
        target_cls, module_result = _receiver_class(
            m, cls, base, meth, local_imports, types
        )
        if module_result is not None:
            return module_result
    elif (
        isinstance(base, ast.Call)
        and isinstance(base.func, ast.Name)
        and base.func.id == "super"
        and cls
    ):
        r = find_method(cls, meth, include_self=False)
        return [("function", r[0], meth)] if r else []
    if target_cls:
        r = find_method(target_cls, meth)
        if r:
            return [("function", r[0], meth)]
        if isinstance(base, ast.Name) and base.id in ("self", "cls"):
            return [("function", rp, meth) for rp in composed_method(target_cls, meth)]
    return []


def callee_targets(m, fn, cls, call, local_imports, types):
    """[(node kind, file, name)] the call resolves to; [] when unresolvable."""
    f = call.func
    if isinstance(f, ast.Name):
        return _name_targets(m, local_imports, f.id)
    if isinstance(f, ast.Attribute):
        return _attribute_targets(m, cls, f, local_imports, types)
    return []


def composed_method(cls, meth):
    """`self.m` inside a mixin: m defined by a sibling base of a class composing the
    mixin."""
    out = set()
    for sub in SUBCLASSES.get((cls[0], cls[1]), ()):
        r = find_method(sub, meth)
        if r:
            out.add(r[0])
    return sorted(out)


SUBCLASSES = {}


def index_subclasses(paths):
    """(mixin path, name) -> classes having it among their transitive bases."""
    for p in paths:
        m = load(p)
        if not m:
            continue
        for cname, cnode in m.classes.items():
            stack, seen = [(p, cname, cnode)], set()
            while stack:
                cur = stack.pop()
                for b in class_bases(cur[0], cur[2]):
                    if (b[0], b[1]) in seen:
                        continue
                    seen.add((b[0], b[1]))
                    stack.append(b)
                    SUBCLASSES.setdefault((b[0], b[1]), []).append((p, cname, cnode))


def call_result_class(m, local_imports, func):
    """Class a call evaluates to: a constructor, or a factory annotated `-> C`."""
    r = None
    if isinstance(func, ast.Name):
        r = resolve_ref(m, local_imports, func.id)
    elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        mp = module_of(m, local_imports, func.value.id)
        r = resolve_symbol(mp, func.attr) if mp else None
    if not r:
        return None
    if isinstance(r[2], ast.ClassDef):
        return r
    if (
        isinstance(r[2], (ast.FunctionDef, ast.AsyncFunctionDef))
        and r[2].returns is not None
    ):
        return ann_class(load(r[0]), {}, r[2].returns)
    return None


def local_types(m, fn, local_imports):
    types = {}
    args = fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs
    for a in args:
        c = ann_class(m, local_imports, a.annotation)
        if c:
            types[a.arg] = c
    for n in ast.walk(fn):
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            c = ann_class(m, local_imports, n.annotation)
            if c:
                types[n.target.id] = c
        elif (
            isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Call)
        ):
            r = call_result_class(m, local_imports, n.value.func)
            if r:
                types[n.targets[0].id] = r
    return types


def references(fn):
    """Function objects passed as values (callbacks, registrations), not called here."""
    called = {id(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for c in ast.walk(fn):
        if isinstance(c, ast.Call):
            for a in list(c.args) + [k.value for k in c.keywords]:
                if (
                    isinstance(a, (ast.Name, ast.Attribute))
                    and id(a) not in called
                    and isinstance(a.ctx, ast.Load)
                ):
                    yield a


def functions(m):
    for n in m.tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield n, None
        elif isinstance(n, ast.ClassDef):
            for b in n.body:
                if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield b, (m.path, n.name, n)
