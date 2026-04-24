"""Codebase graph analysis — import resolution, call graph, communities.

Takes parsed FileAnalysis objects and produces resolved edges:
- File → file import edges (resolved from module names)
- Function → function call edges
- Class → method containment edges
- Class → parent inheritance edges
- Community assignments via Louvain

Pure business logic — no I/O.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from mcp_server.core.codebase_parser import FileAnalysis

# ── Import resolution ─────────────────────────────────────────────────────


def resolve_import_to_file(
    module: str,
    importing_file: str,
    known_files: set[str],
    is_relative: bool = False,
) -> str | None:
    """Resolve a module name to a known file path.

    Args:
        module: Import module name (e.g., "auth.tokens").
        importing_file: Path of the file doing the import.
        known_files: Set of all known file paths in the project.
        is_relative: Whether this is a relative import.

    Returns:
        Resolved file path or None if not found.
    """
    candidates = _build_candidates(module, importing_file, is_relative)
    for candidate in candidates:
        normalized = str(PurePosixPath(candidate))
        if normalized in known_files:
            return normalized
    return None


def _build_candidates(
    module: str,
    importing_file: str,
    is_relative: bool,
) -> list[str]:
    """Build candidate file paths for a module name."""
    candidates: list[str] = []

    if is_relative:
        base_dir = str(PurePosixPath(importing_file).parent)
        clean = module.lstrip(".")
        if clean:
            rel = clean.replace(".", "/")
            candidates.append(f"{base_dir}/{rel}.py")
            candidates.append(f"{base_dir}/{rel}/__init__.py")
    else:
        # Try full path and progressively strip leading segments
        # e.g. ai_architect_mcp._adapters.ports -> _adapters/ports.py
        as_path = module.replace(".", "/")
        _add_path_variants(candidates, as_path)
        parts = as_path.split("/")
        for i in range(1, len(parts)):
            _add_path_variants(candidates, "/".join(parts[i:]))

    return candidates


def _add_path_variants(candidates: list[str], base: str) -> None:
    """Add common file extension variants for a path."""
    candidates.append(f"{base}.py")
    candidates.append(f"{base}/__init__.py")
    candidates.append(f"{base}.ts")
    candidates.append(f"{base}.tsx")
    candidates.append(f"{base}.js")


def resolve_all_imports(
    analyses: list[FileAnalysis],
) -> list[tuple[str, str]]:
    """Resolve imports across all files to file→file edges.

    Returns:
        List of (source_file, target_file) tuples.
    """
    known_files = {a.path for a in analyses}
    edges: list[tuple[str, str]] = []

    for analysis in analyses:
        for imp in analysis.imports:
            target = resolve_import_to_file(
                imp.module, analysis.path, known_files, imp.is_relative
            )
            if target and target != analysis.path:
                edges.append((analysis.path, target))

    return edges


# ── Inheritance extraction ────────────────────────────────────────────────


def extract_inheritance(analyses: list[FileAnalysis]) -> list[tuple[str, str]]:
    """Extract class inheritance edges from definition signatures.

    Returns:
        List of (child_class, parent_class) tuples.
    """
    edges: list[tuple[str, str]] = []
    for analysis in analyses:
        for sym in analysis.definitions:
            if sym.kind == "class" and sym.signature:
                parents = _parse_parent_classes(sym.signature)
                for parent in parents:
                    edges.append((sym.name, parent))
    return edges


def _parse_parent_classes(signature: str) -> list[str]:
    """Parse parent class names from a class signature like '(Base, Mixin)'."""
    clean = signature.strip("()")
    if not clean:
        return []
    parents = []
    for part in clean.split(","):
        name = part.strip().split("[")[0].strip()
        if name and name not in ("object", "ABC", "Protocol"):
            parents.append(name)
    return parents


# ── Call graph ────────────────────────────────────────────────────────────


def build_call_edges(
    analyses: list[FileAnalysis],
    call_sites: dict[str, list[str]],
) -> list[tuple[str, str, str]]:
    """Build function→function call edges.

    Args:
        analyses: All parsed file analyses.
        call_sites: Map of file_path → list of called function names.

    Returns:
        List of (caller_file, called_symbol, defining_file) tuples.
    """
    # Build symbol→file lookup
    symbol_to_file: dict[str, str] = {}
    for analysis in analyses:
        for sym in analysis.definitions:
            base_name = sym.name.split(".")[-1]
            symbol_to_file.setdefault(base_name, analysis.path)

    edges: list[tuple[str, str, str]] = []
    for file_path, calls in call_sites.items():
        for call_name in calls:
            base = call_name.split(".")[-1].split("(")[0]
            target_file = symbol_to_file.get(base)
            if target_file and target_file != file_path:
                edges.append((file_path, base, target_file))

    return edges


def build_resolved_call_edges(
    analyses: list[FileAnalysis],
) -> list[tuple[str, str, str, str]]:
    """Caller-qualified CALLS edges resolved against the known-files set.

    Uses ``FileAnalysis.calls_per_function`` (populated by the
    tree-sitter path in ``ast_parser.parse_file_ast``) to emit edges
    where the SOURCE is a specific function/method — not just the file.
    That is what lets the workflow graph render the full dependency
    chain between methods as part of a file.

    Returns:
        ``[(caller_file, caller_qname, callee_file, callee_basename),
        ...]``. Self-calls (caller and callee in the same file) are
        emitted — they carry the intra-file method-to-method structure
        that the L6 ring renders as short arcs. Unresolved callees
        (stdlib, external deps, dynamic lookups) are dropped silently.
    """
    # Build basename → first-defining-file lookup. First-wins matches
    # the existing `build_call_edges` semantics; collisions across files
    # are rare for user code and intentional for resolution.
    symbol_to_file: dict[str, str] = {}
    for analysis in analyses:
        for sym in analysis.definitions:
            base = sym.name.rsplit(".", 1)[-1]
            symbol_to_file.setdefault(base, analysis.path)

    edges: list[tuple[str, str, str, str]] = []
    for analysis in analyses:
        per_fn = getattr(analysis, "calls_per_function", None) or {}
        for caller_qname, callees in per_fn.items():
            seen_pair: set[tuple[str, str]] = set()
            for call_name in callees:
                base = call_name.rsplit(".", 1)[-1]
                for c in "([<":
                    base = base.split(c, 1)[0]
                base = base.strip()
                if not base:
                    continue
                target_file = symbol_to_file.get(base)
                if target_file is None:
                    continue
                key = (target_file, base)
                if key in seen_pair:
                    continue
                seen_pair.add(key)
                edges.append((analysis.path, caller_qname, target_file, base))
    return edges


# ── Community detection ───────────────────────────────────────────────────


def _build_dependency_graph(
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
) -> object:
    """Build a networkx graph from file and call edges."""
    import networkx as nx

    g = nx.Graph()
    for src, tgt in file_edges:
        g.add_edge(src, tgt, weight=1.0)
    for src, _, tgt in call_edges:
        if g.has_edge(src, tgt):
            g[src][tgt]["weight"] += 0.5
        else:
            g.add_edge(src, tgt, weight=0.5)
    return g


def detect_communities(
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
) -> dict[str, int]:
    """Detect functional communities using Louvain on import+call graph.

    Returns:
        Map of file_path → community_id.
    """
    try:
        import networkx as nx
    except ImportError:
        return {}

    g = _build_dependency_graph(file_edges, call_edges)
    if g.number_of_nodes() < 2:
        return {n: 0 for n in g.nodes()}

    communities = nx.community.louvain_communities(g, weight="weight", seed=42)
    result: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node in community:
            result[node] = idx
    return result


# ── Impact analysis ───────────────────────────────────────────────────────


def compute_impact(
    target_file: str,
    file_edges: list[tuple[str, str]],
    call_edges: list[tuple[str, str, str]],
    max_depth: int = 3,
) -> dict[str, list[str]]:
    """Compute blast radius: what depends on target_file.

    Args:
        target_file: The file being changed.
        file_edges: (source, target) import edges.
        call_edges: (caller, symbol, target) call edges.
        max_depth: Maximum traversal depth.

    Returns:
        Dict with "upstream" and "downstream" file lists.
    """
    # Build adjacency lists
    dependents: dict[str, set[str]] = {}  # target → who imports it
    dependencies: dict[str, set[str]] = {}  # source → what it imports

    for src, tgt in file_edges:
        dependents.setdefault(tgt, set()).add(src)
        dependencies.setdefault(src, set()).add(tgt)
    for src, _, tgt in call_edges:
        dependents.setdefault(tgt, set()).add(src)
        dependencies.setdefault(src, set()).add(tgt)

    upstream = _bfs(target_file, dependents, max_depth)
    downstream = _bfs(target_file, dependencies, max_depth)

    return {
        "upstream": sorted(upstream - {target_file}),
        "downstream": sorted(downstream - {target_file}),
    }


def _bfs(start: str, adj: dict[str, set[str]], max_depth: int) -> set[str]:
    """Breadth-first traversal up to max_depth."""
    visited: set[str] = {start}
    frontier = [start]
    for _ in range(max_depth):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    return visited
