"""Tests for auto_curator — prompt structure + coverage jobs."""

from __future__ import annotations

from mcp_server.core.auto_curator import (
    CurationCluster,
    _ADR_TASK_RECORD_SECTIONS,
    _GENERIC_STRUCTURE_SECTIONS,
    build_authoring_prompt,
    build_clusters,
    build_coverage_jobs,
    build_coverage_prompt,
    build_reauthor_jobs,
    count_pending_clusters_streamed,
    is_path_recently_authored,
    sort_coverage_jobs,
)
from mcp_server.core.wiki_coverage import DomainCoverage, ScopeCoverage, SCOPES


def _cluster(kind: str = "adr") -> CurationCluster:
    return CurationCluster(
        topic="example-feature",
        domain="cortex",
        suggested_kind=kind,
        suggested_path=f"{kind}/cortex/example-feature.md",
        memory_ids=[1, 2, 3, 4],
        memory_contents=["a" * 200, "b" * 200, "c" * 200, "d" * 200],
        memory_tags=[["x"], ["y"], [], []],
        entities=["FeatureX", "feature_y"],
        avg_heat=0.5,
        earliest_at="2026-05-01",
        latest_at="2026-05-17",
    )


class TestAuthoringPromptKindSpecificSections:
    """The prompt must require Entry/Mandatory/How/Result/Serves for ADRs."""

    def test_adr_prompt_carries_task_record_section_block(self):
        prompt = build_authoring_prompt(_cluster("adr"), related_pages=[])
        for token in (
            "## Status",
            "## Entry",
            "## Mandatory elements",
            "## How",
            "## Result",
            "## Serves",
            "## Alternatives considered",
            "## References",
        ):
            assert token in prompt, f"ADR prompt missing required section: {token}"

    def test_non_adr_prompt_uses_generic_structure(self):
        prompt = build_authoring_prompt(_cluster("reference"), related_pages=[])
        # Generic structure → no Entry/Mandatory/Result/Serves required.
        assert "## Entry" not in prompt
        assert "## Mandatory elements" not in prompt
        # But it MUST carry the conventional architecture sections.
        assert "Why this design and not the alternatives" in prompt
        assert "What can go wrong" in prompt

    def test_kind_specific_section_constants_distinct(self):
        assert _ADR_TASK_RECORD_SECTIONS != _GENERIC_STRUCTURE_SECTIONS
        assert "Entry" in _ADR_TASK_RECORD_SECTIONS
        assert "Entry" not in _GENERIC_STRUCTURE_SECTIONS


class TestCoveragePrompt:
    def test_coverage_prompt_names_scope_and_path(self):
        prompt = build_coverage_prompt(
            scope_name="architecture",
            scope_title="Architecture overview",
            scope_description="The overall design.",
            suggested_kind="explanation",
            suggested_path="reference/cortex/architecture-overview.md",
            domain="cortex",
            related_pages=["reference/cortex/api.md"],
            supporting_memories=["mem 1 body"],
            supporting_tags=[["arch"]],
            today="2026-05-18",
        )
        assert "architecture" in prompt
        assert "Architecture overview" in prompt
        assert "reference/cortex/architecture-overview.md" in prompt
        assert "cortex" in prompt
        # Cross-link block uses [[wiki/path]] notation.
        assert "[[reference/cortex/api.md]]" in prompt


def _scope_by_name(name: str):
    """Look up a Scope by name — robust to catalogue reorder.

    The SCOPES tuple grew from 6 to 15 entries when more canonical
    documentation slots were added; positional indexing broke the
    tests. Lookup by name keeps assertions stable across catalogue
    additions.
    """
    for s in SCOPES:
        if s.name == name:
            return s
    raise KeyError(f"no scope named {name!r}")


class TestCoverageJobBuilder:
    def test_emits_one_job_per_missing_scope(self):
        # Domain with 2 missing scopes → 2 jobs.
        missing_arch = ScopeCoverage(
            scope=_scope_by_name("architecture"),
            domain="cortex",
            covered=False,
            page_count=0,
            anchor_page=None,
            suggested_path="reference/cortex/architecture-overview.md",
        )
        missing_api = ScopeCoverage(
            scope=_scope_by_name("api"),
            domain="cortex",
            covered=False,
            page_count=0,
            anchor_page=None,
            suggested_path="reference/cortex/api.md",
        )
        cov = DomainCoverage(domain="cortex", scopes=[missing_arch, missing_api])
        jobs = build_coverage_jobs([cov])
        assert len(jobs) == 2
        assert {j.scope_name for j in jobs} == {"architecture", "api"}

    def test_sort_by_structural_primacy(self):
        # Mix of architecture, api, data-flow — architecture must come first.
        scope_names = ["data-flow", "api", "architecture"]
        covs = []
        for name in scope_names:
            s = _scope_by_name(name)
            sc = ScopeCoverage(
                scope=s,
                domain="cortex",
                covered=False,
                page_count=0,
                anchor_page=None,
                suggested_path=f"reference/cortex/{s.name}.md",
            )
            covs.append(DomainCoverage(domain="cortex", scopes=[sc]))
        jobs = sort_coverage_jobs(build_coverage_jobs(covs))
        names = [j.scope_name for j in jobs]
        assert names == ["architecture", "api", "data-flow"]


class _FakeWikiPagePort:
    """Records every call — proves core delegates through the injected
    ``WikiPagePort`` and never performs filesystem I/O itself (issue
    #314). No ``tmp_path``/real file appears anywhere in this class or
    its callers below; a real ``FsWikiPagePort`` is exercised separately
    in ``tests_py/infrastructure/test_wiki_page_fs.py``.
    """

    def __init__(
        self,
        *,
        fresh: frozenset[str] = frozenset(),
        texts: dict[str, str] | None = None,
    ) -> None:
        self._fresh = fresh
        self._texts = texts or {}
        self.is_recently_modified_calls: list[tuple[str, int]] = []
        self.read_text_calls: list[str] = []

    def is_recently_modified(self, rel_path: str, within_days: int) -> bool:
        self.is_recently_modified_calls.append((rel_path, within_days))
        return rel_path in self._fresh

    def read_text(self, rel_path: str) -> str | None:
        self.read_text_calls.append(rel_path)
        return self._texts.get(rel_path)


class _Drift:
    """Minimal stand-in for ``wiki_drift.PageDrift`` — only the fields
    ``build_reauthor_jobs``/``build_reauthor_prompt`` read."""

    def __init__(
        self, wiki_path: str, domain: str = "cortex", kind: str = "reference"
    ) -> None:
        self.wiki_path = wiki_path
        self.domain = domain
        self.kind = kind
        self.reasons: list[str] = ["stale_content"]
        self.missing_source_files: list[str] = []
        self.cited_source_files: list[str] = []
        self.last_updated = ""
        self.age_days = 40.0


def _memory(mid: int, content: str, heat: float = 0.5) -> dict:
    return {
        "id": mid,
        "content": content,
        "tags": [],
        "effective_heat": heat,
        "domain": "cortex",
        "created_at": "2026-05-01",
    }


_ENTITY_MEMORIES = [
    _memory(i, f"predictive_coding_gate detail {i} predictive_coding_gate")
    for i in range(5)
]
_ENTITY_SUGGESTED_PATH = "reference/cortex/predictive-coding-gate.md"


class TestWikiPagePortDIP:
    """core/auto_curator.py declares ``WikiPagePort`` and delegates every
    filesystem-shaped decision to the injected instance (issue #314) —
    it performs zero I/O itself."""

    def test_is_path_recently_authored_delegates_to_port(self):
        port = _FakeWikiPagePort(fresh=frozenset({"reference/cortex/x.md"}))
        assert is_path_recently_authored("reference/cortex/x.md", port) is True
        assert is_path_recently_authored("reference/cortex/y.md", port) is False
        assert port.is_recently_modified_calls == [
            ("reference/cortex/x.md", 30),
            ("reference/cortex/y.md", 30),
        ]

    def test_build_clusters_skips_fresh_pages_via_port(self):
        fresh_port = _FakeWikiPagePort(fresh=frozenset({_ENTITY_SUGGESTED_PATH}))
        clusters = build_clusters(_ENTITY_MEMORIES, wiki_page_port=fresh_port)
        assert clusters == []
        assert fresh_port.is_recently_modified_calls  # the port was consulted

    def test_build_clusters_keeps_stale_pages_via_port(self):
        stale_port = _FakeWikiPagePort()
        clusters = build_clusters(_ENTITY_MEMORIES, wiki_page_port=stale_port)
        assert len(clusters) == 1
        assert stale_port.is_recently_modified_calls == [(_ENTITY_SUGGESTED_PATH, 30)]

    def test_build_clusters_skips_no_filtering_without_a_port(self):
        # No port injected → freshness filter is skipped entirely, same
        # as the pre-refactor `if skip_recently_authored and wiki_root:`
        # guard when wiki_root was falsy.
        clusters = build_clusters(_ENTITY_MEMORIES)
        assert len(clusters) == 1

    def test_count_pending_clusters_streamed_uses_injected_port(self):
        port = _FakeWikiPagePort(fresh=frozenset({_ENTITY_SUGGESTED_PATH}))
        assert (
            count_pending_clusters_streamed([_ENTITY_MEMORIES], wiki_page_port=port)
            == 0
        )
        assert port.is_recently_modified_calls

    def test_build_reauthor_jobs_reads_via_port_not_filesystem(self):
        port = _FakeWikiPagePort(texts={"reference/cortex/a.md": "# A\n\nold body"})
        drifts = [
            _Drift("reference/cortex/a.md"),
            _Drift("reference/cortex/missing.md"),
        ]
        jobs = build_reauthor_jobs(
            drifts, wiki_page_port=port, source_root_resolver=lambda _d: None
        )
        # Only the drift whose text the port returns becomes a job — the
        # missing one is silently skipped, matching pre-refactor semantics
        # (the old code caught OSError from `open()` and did `continue`).
        assert [j.wiki_path for j in jobs] == ["reference/cortex/a.md"]
        assert port.read_text_calls == [
            "reference/cortex/a.md",
            "reference/cortex/missing.md",
        ]

    def test_count_pending_clusters_streamed_skips_filter_without_a_port(self):
        # Mutation-driven (§12): `skip_recently_authored and wiki_page_port
        # is not None` mutated to `or` would call
        # `is_path_recently_authored(path, None)` here — an
        # AttributeError on `None.is_recently_modified(...)`, not a
        # silent skip. No port injected → the guard must short-circuit
        # before ever touching the port.
        assert count_pending_clusters_streamed([_ENTITY_MEMORIES]) == 1
