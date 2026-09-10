"""Domain mapping — resolves paths, slugs, and hints to canonical domain names.

source: ADR-0647"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import os as _os

# source: ADR-0647

_MIN_MEANINGFUL_FRAGMENT_CHARS = 4

# source: ADR-0647
# source: ADR-0647
_MIN_SLUG_CHARS = 10


@dataclass
class RepoInfo:
    fs_path: str
    dir_name: str
    remote_name: str
    canonical: str = ""


def _to_posix(path: Path) -> str:
    """Canonical forward-slash string form of a filesystem path.

    precondition: none — accepts any ``Path``, resolved or not.
    postcondition: returns ``str(path)`` with backslashes normalized to
    forward slashes. On POSIX this is a no-op (paths never contain
    backslashes); on Windows it matches the form ``git`` itself prints
    (and that ``_git_root`` already normalizes to).

    source: ADR-0647"""
    return str(path).replace("\\", "/")


# ── Step 1: Discover git repos ────────────────────────────────────────


def _get_remote_url(repo_path: Path) -> str:
    """Get git remote origin URL by parsing ``.git/config`` directly.

    precondition: ``repo_path`` is a directory whose ``.git`` child is a
    directory (a normal clone — the only shape ``_discover_repos`` passes
    in; linked worktrees have a ``.git`` *file* and are never routed here).
    postcondition: returns the ``url`` value of the ``[remote "origin"]``
    section, or ``''`` if the config file, the section, or the key is
    absent. Never raises.

    source: ADR-0647"""
    try:
        cfg = repo_path / ".git" / "config"
        if not cfg.is_file():
            return ""
        section = ""
        for raw in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("["):
                section = line.lower()
            elif section == '[remote "origin"]' and line.lower().startswith("url"):
                _, _, value = line.partition("=")
                if value.strip():
                    return value.strip()
        return ""
    except OSError:
        return ""


def _extract_repo_name(url: str) -> str:
    """Extract repo name from remote URL.

    'github.com/cdeust/Cortex.git' → 'cortex'
    'github.com/cdeust/ai-architect-pipeline.git' → 'ai-architect-pipeline'
    """
    if not url:
        return ""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name.lower()


def _discover_repos(dev_root: Path) -> list[RepoInfo]:
    """Scan for git repos under dev_root (2 levels deep)."""
    repos: list[RepoInfo] = []
    if not dev_root.is_dir():
        return repos
    for item in dev_root.iterdir():
        if not item.is_dir() or item.name.startswith("."):
            continue
        if (item / ".git").is_dir():
            remote = _get_remote_url(item)
            repos.append(
                RepoInfo(
                    fs_path=_to_posix(item),
                    dir_name=item.name.lower(),
                    remote_name=_extract_repo_name(remote) or item.name.lower(),
                )
            )
        # One level deeper for org dirs (e.g., anthropic/ai-architect-mcp-codebase)
        else:
            for sub in item.iterdir():
                if sub.is_dir() and (sub / ".git").is_dir():
                    remote = _get_remote_url(sub)
                    repos.append(
                        RepoInfo(
                            fs_path=_to_posix(sub),
                            dir_name=sub.name.lower(),
                            remote_name=_extract_repo_name(remote) or sub.name.lower(),
                        )
                    )
    return repos


# ── Step 2: Group repos by shared remote-name prefix ─────────────────


def _shared_prefix(a: str, b: str) -> str:
    """Find the longest shared hyphen-delimited prefix between two names.

    'ai-architect-pipeline' and 'ai-architect-prd-builder' → 'ai-architect'
    'cortex' and 'cortex-cowork' → 'cortex'
    'career-ops' and 'memory-monitor' → '' (no shared prefix)
    """
    parts_a = a.split("-")
    parts_b = b.split("-")
    common: list[str] = []
    # source: ADR-0647

    for pa, pb in zip(parts_a, parts_b, strict=False):
        if pa == pb:
            common.append(pa)
        else:
            break
    prefix = "-".join(common)
    # Require prefix to be meaningful: at least 4 chars
    # This allows "cortex" (6 chars, 1 segment) to group cortex-cowork
    # but rejects "ai" (2 chars) from falsely grouping unrelated ai-* repos
    return prefix if len(prefix) >= _MIN_MEANINGFUL_FRAGMENT_CHARS else ""


def _group_repos(repos: list[RepoInfo]) -> dict[str, str]:
    """Group repos by shared remote-name prefix. Return name→canonical mapping.

    Uses pairwise prefix detection: if two repos share a prefix of >= 2
    hyphen segments, they belong to the same family. The shared prefix
    becomes the canonical name.
    """
    # Collect all names
    all_names = [(r.remote_name, r) for r in repos]

    # Find all pairwise shared prefixes
    prefix_groups: dict[str, set[str]] = {}  # prefix → set of names
    for i in range(len(all_names)):
        for j in range(i + 1, len(all_names)):
            prefix = _shared_prefix(all_names[i][0], all_names[j][0])
            if prefix:  # _shared_prefix already enforces >= 4 chars
                prefix_groups.setdefault(prefix, set()).update(
                    {all_names[i][0], all_names[j][0]}
                )

    # Merge overlapping groups (if name appears in multiple prefix groups,
    # use longest prefix)
    name_to_canonical: dict[str, str] = {}
    for prefix, members in sorted(prefix_groups.items(), key=lambda x: -len(x[0])):
        for member in members:
            if member not in name_to_canonical:
                name_to_canonical[member] = prefix

    # Assign canonical to repos and register dir_names
    for repo in repos:
        rn = repo.remote_name
        if rn in name_to_canonical:
            repo.canonical = name_to_canonical[rn]
        else:
            # Standalone repo — canonical is itself
            repo.canonical = rn
            name_to_canonical[rn] = rn

        # Also register dir_name → canonical
        if repo.dir_name != rn and repo.dir_name not in name_to_canonical:
            name_to_canonical[repo.dir_name] = repo.canonical

    return name_to_canonical


# ── Step 3: Build slug decoder ────────────────────────────────────────


def _build_slug_index(repos: list[RepoInfo]) -> dict[str, RepoInfo]:
    """Map slug-encoded repo paths to RepoInfo for prefix matching."""
    index: dict[str, RepoInfo] = {}
    for repo in repos:
        # Encode the real path as a slug (same encoding Claude uses)
        slug = repo.fs_path.replace("/", "-").lstrip("-").lower()
        index[slug] = repo
    return index


def _match_slug(slug: str, slug_index: dict[str, RepoInfo]) -> RepoInfo | None:
    """Match a project slug against known repo slugs by longest prefix."""
    clean = slug.lstrip("-").lower()
    # Strip worktree noise: slug contains "--" before worktree suffix
    if "--" in clean:
        clean = clean.split("--")[0]
    # Also strip at "-worktrees-" if present without double dash
    if "-worktrees-" in clean:
        clean = clean[: clean.index("-worktrees-")]

    best: RepoInfo | None = None
    best_len = 0
    for known_slug, repo in slug_index.items():
        if clean.startswith(known_slug) and len(known_slug) > best_len:
            best = repo
            best_len = len(known_slug)
    return best


# ── Step 4: Build fragment index ──────────────────────────────────────


def _build_fragment_index(
    repos: list[RepoInfo],
    name_to_canonical: dict[str, str],
) -> dict[str, str]:
    """Map meaningful fragments to canonical names.

    For each repo, generate all contiguous sub-sequences of hyphen-delimited
    parts (length >= 4 chars). Longer fragments win ties.
    """
    fragments: dict[str, tuple[str, int]] = {}  # fragment → (canonical, length)

    for repo in repos:
        canonical = repo.canonical
        for name in {repo.dir_name, repo.remote_name}:
            parts = name.split("-")
            for i in range(len(parts)):
                for j in range(i + 1, len(parts) + 1):
                    fragment = "-".join(parts[i:j])
                    if len(fragment) < _MIN_MEANINGFUL_FRAGMENT_CHARS:
                        continue
                    existing = fragments.get(fragment)
                    if existing is None or len(fragment) > existing[1]:
                        fragments[fragment] = (canonical, len(fragment))

    return {k: v[0] for k, v in fragments.items()}


# ── Step 5: Git root resolution ───────────────────────────────────────


def _git_root(path: str) -> str | None:
    """Find the git repo root for a path by walking up to the nearest ``.git``.

    precondition: path is a string and need not exist.
    postcondition: returns the normalized absolute nearest ancestor with
    a .git directory or worktree gitdir file. Returns None when no ancestor
    exists or resolution fails. GIT_DIR/GIT_WORK_TREE overrides and bare
    repositories are unsupported.
    source: ADR-0647"""
    try:
        candidate = Path(path).resolve()
    except OSError:
        return None
    for ancestor in (candidate, *candidate.parents):
        if (ancestor / ".git").exists():
            return str(ancestor).replace("\\", "/")
    return None


def _dereference_worktree_gitdir(git_entry: Path) -> Path | None:
    """Resolve a linked worktree's ``.git`` file to its main repo's root.

    precondition: git_entry is the .git path under the discovered root.
    postcondition: returns the main repository root for a well-formed linked
    worktree gitdir file. Returns None for directories, missing, unreadable,
    empty, malformed, relocated, or non-worktree entries. Never raises;
    performs filesystem reads without subprocess calls.
    source: ADR-0647"""
    if not git_entry.is_file():
        return None
    try:
        text = git_entry.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    raw = text[len("gitdir:") :].strip()
    if not raw:
        return None
    gitdir_path = Path(raw)
    if not gitdir_path.is_absolute():
        gitdir_path = git_entry.parent / gitdir_path
    try:
        gitdir_path = gitdir_path.resolve()
    except OSError:
        return None
    # Expected shape: <main>/.git/worktrees/<name>
    worktrees_dir = gitdir_path.parent
    if worktrees_dir.name != "worktrees":
        return None
    git_dir = worktrees_dir.parent
    if git_dir.name != ".git":
        return None
    main_root = git_dir.parent
    if not (main_root / ".git").is_dir():
        return None
    return main_root


def _resolve_repo_for_root(root: str, registry: DomainRegistry) -> RepoInfo | None:
    """Look up the registered repo for a git root, dereferencing worktrees.

    precondition: root is the normalized nearest Git root; registry is the
    current DomainRegistry.
    postcondition: returns registered RepoInfo directly for known roots;
    linked worktrees resolve to their registered main repository's RepoInfo.
    Returns None for unregistered roots or unresolvable worktree pointers.
    source: ADR-0647"""
    repo = registry.path_to_repo.get(root)
    if repo is not None:
        return repo
    main_root = _dereference_worktree_gitdir(Path(root) / ".git")
    if main_root is None:
        return None
    return registry.path_to_repo.get(_to_posix(main_root))


# ── Registry ──────────────────────────────────────────────────────────


@dataclass
class DomainRegistry:
    repos: list[RepoInfo]
    name_to_canonical: dict[str, str]
    slug_index: dict[str, RepoInfo]
    fragment_index: dict[str, str]
    path_to_repo: dict[str, RepoInfo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path_to_repo = {r.fs_path: r for r in self.repos}


def _candidate_dev_roots() -> list[Path]:
    """Plausible parent directories for the user's git repos.

    Probed in order:
      1. ``$CORTEX_DEV_ROOT`` env var — explicit override.
      2. ``~/Developments`` — original assumption.
      3. ``~/Documents/Developments`` — the common macOS Documents-nested layout.
      4. ``~/dev`` and ``~/code`` — common alternative parents.

    source: ADR-0647"""

    cands: list[Path] = []
    env = _os.environ.get("CORTEX_DEV_ROOT")
    if env:
        cands.append(Path(env))
    home = Path.home()
    cands.extend(
        [
            home / "Developments",
            home / "Documents" / "Developments",
            home / "dev",
            home / "code",
        ]
    )
    return [c for c in cands if c.is_dir()]


@lru_cache(maxsize=1)
def _build_registry() -> DomainRegistry:
    """Build the complete domain registry from git repos. Cached at startup.

    source: ADR-0647"""
    repos: list[RepoInfo] = []
    seen_paths: set[str] = set()
    for dev_root in _candidate_dev_roots():
        for r in _discover_repos(dev_root):
            if r.fs_path in seen_paths:
                continue
            seen_paths.add(r.fs_path)
            repos.append(r)
    name_to_canonical = _group_repos(repos)
    slug_index = _build_slug_index(repos)
    fragment_index = _build_fragment_index(repos, name_to_canonical)
    return DomainRegistry(repos, name_to_canonical, slug_index, fragment_index)


# ── Public API ────────────────────────────────────────────────────────


def resolve_domain(input_str: str) -> str:
    """Resolve any input to a canonical domain name.

    Handles:
    - Filesystem paths: /Users/cdeust/Developments/Cortex/mcp_server
    - Project slugs: -Users-cdeust-Developments-Cortex
    - Domain hints: 'cortex', 'ai-architect'
    - Broken fragments: 'architect', 'builder', 'loop'
    """
    if not input_str or not input_str.strip():
        return ""

    registry = _build_registry()
    clean = input_str.strip()

    # 1. Is it a filesystem path? → git_root → repo match
    if "/" in clean and not clean.startswith("-"):
        root = _git_root(clean)
        if root:
            repo = _resolve_repo_for_root(root, registry)
            if repo:
                return repo.canonical
        # Try prefix match against known repo paths
        for repo in registry.repos:
            if clean.startswith(repo.fs_path):
                return repo.canonical

    # 2. Is it a slug? (starts with - and looks path-like)
    if clean.startswith("-") and len(clean) > _MIN_SLUG_CHARS:
        repo = _match_slug(clean, registry.slug_index)
        if repo:
            return repo.canonical

    # 3. Exact match against known names
    lower = clean.lower()
    if lower in registry.name_to_canonical:
        return registry.name_to_canonical[lower]

    # 4. Fragment match — longest known fragment that is a substring of input
    if lower in registry.fragment_index:
        return registry.fragment_index[lower]

    # Also check if any known fragment is a substring of the input
    best_frag = ""
    best_frag_len = 0
    for frag, canonical in registry.fragment_index.items():
        if (
            len(frag) >= _MIN_MEANINGFUL_FRAGMENT_CHARS
            and frag in lower
            and len(frag) > best_frag_len
        ):
            best_frag = canonical
            best_frag_len = len(frag)
    if best_frag:
        return best_frag

    # source: ADR-0647

    if clean.startswith("-"):
        stripped = lower
        for prefix in (
            "-users-cdeust-developments-",
            "-users-cdeust-documents-",
            "-users-cdeust-",
        ):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :]
                break
        # Strip worktree suffixes that survived (no slug match found above).
        if "-worktrees-" in stripped:
            stripped = stripped[: stripped.index("-worktrees-")]
        # First hyphen-segment is the most meaningful tail (e.g. "jarvis"
        # from "-Users-cdeust-Developments-jarvis"). Multi-segment tails
        # (e.g. "ai-architect-prd-builder") collapse via earlier slug match.
        return stripped.split("-", 1)[0] if stripped else lower
    return lower


def resolve_cwd(cwd: str) -> str:
    """Resolve a working directory to a canonical domain.

    This is the primary domain resolution path (Shannon: cwd is the
    minimum sufficient statistic for domain identity).

    Returns '' if the cwd does not belong to a *known* repo — callers
    rely on empty-string to fall through to explicit domain hints.
    """
    if not cwd:
        return ""
    root = _git_root(cwd)
    if root:
        registry = _build_registry()
        repo = _resolve_repo_for_root(root, registry)
        if repo:
            return repo.canonical
    # source: ADR-0647

    return ""
