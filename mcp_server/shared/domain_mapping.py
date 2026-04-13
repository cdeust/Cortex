"""Domain mapping — resolves paths, slugs, and hints to canonical domain names.

Builds the mapping dynamically from git repos discovered on the filesystem.
No hardcoded domain list — git remote URLs are the structural invariant
(they survive renames, moves, worktree creation).

Algorithm (Rejewski + Shannon):
  1. Discover git repos under ~/Developments
  2. Group related repos by shared remote-URL name prefix
  3. Build a slug decoder (encode known paths as slugs, match by prefix)
  4. Build a fragment index (all substrings of known names)
  5. Resolve: cwd → git_root → longest prefix match → canonical name

Pure business logic — uses subprocess only for `git remote get-url origin`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass
class RepoInfo:
    fs_path: str
    dir_name: str
    remote_name: str
    canonical: str = ""


# ── Step 1: Discover git repos ────────────────────────────────────────


def _get_remote_url(repo_path: Path) -> str:
    """Get git remote origin URL. Returns '' if no remote."""
    try:
        return (
            subprocess.check_output(
                ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
    except Exception:
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
                    fs_path=str(item),
                    dir_name=item.name.lower(),
                    remote_name=_extract_repo_name(remote) or item.name.lower(),
                )
            )
        # One level deeper for org dirs (e.g., anthropic/ai-automatised-pipeline)
        else:
            for sub in item.iterdir():
                if sub.is_dir() and (sub / ".git").is_dir():
                    remote = _get_remote_url(sub)
                    repos.append(
                        RepoInfo(
                            fs_path=str(sub),
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
    for pa, pb in zip(parts_a, parts_b):
        if pa == pb:
            common.append(pa)
        else:
            break
    prefix = "-".join(common)
    # Require prefix to be meaningful: at least 4 chars
    # This allows "cortex" (6 chars, 1 segment) to group cortex-cowork
    # but rejects "ai" (2 chars) from falsely grouping unrelated ai-* repos
    return prefix if len(prefix) >= 4 else ""


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

    # Merge overlapping groups (if name appears in multiple prefix groups, use longest prefix)
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
                    if len(fragment) < 4:
                        continue
                    existing = fragments.get(fragment)
                    if existing is None or len(fragment) > existing[1]:
                        fragments[fragment] = (canonical, len(fragment))

    return {k: v[0] for k, v in fragments.items()}


# ── Step 5: Git root resolution ───────────────────────────────────────


def _git_root(path: str) -> str | None:
    """Find the git repo root for a path. Returns None if not in a repo."""
    try:
        return (
            subprocess.check_output(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            .decode()
            .strip()
        )
    except Exception:
        return None


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


@lru_cache(maxsize=1)
def _build_registry() -> DomainRegistry:
    """Build the complete domain registry from git repos. Cached at startup."""
    dev_root = Path.home() / "Developments"
    repos = _discover_repos(dev_root)
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
        if root and root in registry.path_to_repo:
            return registry.path_to_repo[root].canonical
        # Try prefix match against known repo paths
        for repo in registry.repos:
            if clean.startswith(repo.fs_path):
                return repo.canonical

    # 2. Is it a slug? (starts with - and looks path-like)
    if clean.startswith("-") and len(clean) > 10:
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
        if len(frag) >= 4 and frag in lower and len(frag) > best_frag_len:
            best_frag = canonical
            best_frag_len = len(frag)
    if best_frag:
        return best_frag

    # 5. No match — return lowercased as-is
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
        repo = registry.path_to_repo.get(root)
        if repo:
            return repo.canonical
    # If not in a known git repo, return '' so callers can fall through
    # to explicit domain hints.  The old behaviour delegated to
    # resolve_domain(cwd) which *always* returns non-empty (it falls
    # back to the lowercased input), silently overriding any explicit
    # domain the caller intended to use.
    return ""
