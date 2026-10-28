"""Wiki authoring jobs retain qualifying evidence and deduplicate cross-links.

source: ADR-0108 and auto_curator's streaming/authoring public contracts.
"""

from types import SimpleNamespace

from mcp_server.core.auto_curator import (
    MAX_MEMORIES_PER_PROMPT,
    build_clusters,
    build_coverage_jobs,
    build_jobs,
    build_reauthor_prompt,
    count_pending_clusters,
    count_pending_clusters_streamed,
)
from mcp_server.core.wiki_coverage import DomainCoverage, ScopeCoverage, SCOPES


def _memories(topic, *, count=4, heat=0.5, domain="cortex", tags=()):
    return [
        {
            "id": index,
            "content": f"{topic} evidence {index}",
            "domain": domain,
            "tags": list(tags),
            "heat": heat,
            "created_at": f"2026-05-0{index + 1}",
        }
        for index in range(count)
    ]


def test_streamed_count_and_jobs_agree_after_filtering_and_kind_selection():
    memories = (
        _memories("StableStore", tags=("Decision",))
        + _memories("PastFailure", tags=("Learned",))
        + _memories("RareTopic", count=1)
        + _memories("ColdTopic", heat=0.1)
        + _memories("OtherDomain", domain="other")
        + [
            {
                "id": 100,
                "content": "ordinary words without identifiers",
                "domain": "cortex",
            }
        ]
    )
    clusters = build_clusters(memories, domain="cortex")
    assert {(c.topic, c.suggested_kind) for c in clusters} == {
        ("StableStore", "adr"),
        ("PastFailure", "lesson"),
    }
    chunks = (memories[start : start + 3] for start in range(0, len(memories), 3))
    assert count_pending_clusters_streamed(chunks, domain="cortex") == 2
    assert count_pending_clusters(memories, domain="cortex") == 2
    assert build_clusters([]) == []
    for cluster in clusters:
        assert cluster.earliest_at == "2026-05-01"
        assert cluster.latest_at == "2026-05-04"
        assert cluster.memory_ids == [0, 1, 2, 3]


def test_cluster_jobs_link_related_pages_once_and_mark_truncated_evidence():
    cluster = build_clusters(_memories("StableStore", tags=("decision",)))[0]
    cluster.memory_contents = ["opening evidence " + "x" * 1300, "second evidence"]
    cluster.memory_tags = [["decision"]]
    related = "reference/cortex/storage.md"
    jobs = build_jobs(
        [cluster],
        {
            "StableStore": [cluster.suggested_path, related, related],
            "unrelated": ["reference/other.md"],
        },
        today="2026-10-23",
    )
    assert len(jobs) == 1
    job = jobs[0]
    assert job.cluster is cluster
    assert job.related_pages == [related]
    assert job.prompt.count(f"[[{related}]]") == 1
    assert "created: 2026-10-23" in job.prompt
    assert "opening evidence" in job.prompt
    assert "[memory truncated, full content available via recall]" in job.prompt
    assert "Memory 2 (tags: (no tags))" in job.prompt
    assert "second evidence" in job.prompt


def test_scope_job_uses_only_its_domain_evidence_and_relevant_links():
    scope = next(s for s in SCOPES if s.name == "api")
    coverage = DomainCoverage(
        domain="cortex",
        scopes=[
            ScopeCoverage(
                scope=scope,
                domain="cortex",
                covered=False,
                page_count=0,
                anchor_page=None,
                suggested_path="reference/cortex/api.md",
            )
        ],
    )
    memories = _memories("ApiContract", count=MAX_MEMORIES_PER_PROMPT + 1)
    (job,) = build_coverage_jobs(
        [coverage],
        existing_pages_by_topic={
            "Cortex internals": ["reference/cortex/internals.md"],
            "API": ["reference/cortex/internals.md", "reference/api/types.md"],
            "unrelated": ["reference/private.md"],
        },
        supporting_memories_by_domain={
            "cortex": memories,
            "other": [{"content": "PRIVATE"}],
        },
        today="2026-10-23",
    )
    assert job.related_pages == [
        "reference/cortex/internals.md",
        "reference/api/types.md",
    ]
    assert job.supporting_memory_ids == [m["id"] for m in memories]
    assert f"ApiContract evidence {MAX_MEMORIES_PER_PROMPT - 1}" in job.prompt
    assert f"ApiContract evidence {MAX_MEMORIES_PER_PROMPT}" not in job.prompt
    assert "PRIVATE" not in job.prompt


def test_reauthor_prompt_explains_missing_sources_and_required_repair():
    drift = SimpleNamespace(
        reasons=["missing_source_file", "off_template"],
        missing_source_files=["src/removed.py"],
        cited_source_files=["src/removed.py"],
        age_days=0,
        last_updated="2026-05-01",
        kind="adr",
        domain="cortex",
        wiki_path="adr/cortex/storage.md",
    )
    prompt = build_reauthor_prompt(
        drift, "Retain verified original claim.", "/project", today="2026-10-23"
    )
    assert "src/removed.py" in prompt
    assert "Missing source files" in prompt
    assert "Off-template" in prompt
    assert "Restore the canonical structure" in prompt
    assert "Retain verified original claim." in prompt
    assert "/project" in prompt
