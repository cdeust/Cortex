"""ADR-0124: resolution preserves chronology, provenance and explicit overrides."""

from copy import deepcopy
import pytest
from mcp_server.core.claim_resolver import plan_conflicts, plan_supersedes, resolve


def claim(identifier, kind="decision", *, when=1, entities=(7,), **changes):
    return {
        "id": identifier,
        "claim_type": kind,
        "text": "Redis backs the cache",
        "entity_ids": list(entities),
        "extracted_at": when,
        **changes,
    }


def test_resolution_links_evidence_and_selects_latest_compatible_prior():
    new = claim(
        10,
        "method",
        when=4,
        memory_id=100,
        text="Redis replaces the old cache",
        entities=(),
    )
    original = deepcopy(new)
    priors = [
        claim(1, when=1),
        claim(2, when=3),
        claim(3, when=5),
        claim(4, "limitation", when=3),
        new,
    ]
    links, supersedes, conflicts, stats = resolve(
        [new],
        entities_by_memory={100: [7, 7]},
        prior_claims_by_entity={7: priors},
        entity_name_to_id={"Redis": 7, "Re": 99},
    )
    assert links[0].entity_ids == [7]
    assert [(p.new_claim_id, p.superseded_claim_id) for p in supersedes] == [(10, 2)]
    assert not conflicts
    assert (
        stats.claims_processed
        == stats.entity_links_planned
        == stats.supersedes_planned
        == 1
    )
    assert new == original


@pytest.mark.parametrize(
    "changes",
    [
        {"supersedes": 1},
        {"claim_type": "observation"},
        {"entity_ids": []},
        {"text": "Redis remains useful"},
    ],
)
def test_no_speculative_supersession_without_eligible_signal_and_provenance(changes):
    new = (
        claim(10, when=4, text="Redis replaces the old cache", **changes)
        if "text" not in changes
        else claim(10, when=4, **changes)
    )
    assert plan_supersedes([new], {7: [claim(1)]}) == []


def test_nonmatching_priors_and_newer_claims_do_not_create_backwards_edges():
    new = claim(10, when=4, text="Redis replaces the old cache")
    assert (
        plan_supersedes([new], {7: [new, claim(2, when=5), claim(3, "limitation")]})
        == []
    )


def test_conflicts_are_symmetric_deduplicated_and_honor_explicit_resolution():
    decision = claim(1, entities=(7, 8))
    limitation = claim(2, "limitation", entities=(7, 8))
    priors = {
        7: [decision, limitation, {"id": None}, claim(3, entities=(9,))],
        8: [limitation, decision],
    }
    plans = plan_conflicts([decision, limitation], priors, min_entity_overlap=2)
    assert [(p.claim_a_id, p.claim_b_id, p.overlap_entities) for p in plans] == [
        (1, 2, [7, 8])
    ]
    assert "limitation" in plans[0].reason
    resolved = claim(2, "limitation", supersedes=1)
    assert plan_conflicts([decision], {7: [resolved]}) == []
    assert plan_conflicts([resolved, {"id": None}], priors) == []


def test_entity_name_boundaries_do_not_link_substrings_or_short_names():
    links, _, _, stats = resolve(
        [claim(1, text="Redish is not a known system")],
        entities_by_memory={},
        prior_claims_by_entity={},
        entity_name_to_id={"Redis": 7, "is": 8},
    )
    assert links[0].entity_ids == []
    assert stats.entity_links_planned == 0
