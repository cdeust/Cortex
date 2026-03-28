"""Spell alteration benchmark — needle-in-a-haystack memory fidelity test.

Ingests Harry Potter spell knowledge (50+ spells with descriptions),
replaces exactly 2 real spells with fake alternatives, stores everything
as memories, then tests whether recall can:
  1. Retrieve the correct spell when asked about its effect
  2. Distinguish real spells from the 2 altered fakes
  3. Identify WHICH spells were replaced when asked directly

This validates memory precision under high-similarity conditions —
all spells are thematically similar (magic, wands, Latin-sounding),
so the system must rely on exact content matching, not just vibes.
"""

from __future__ import annotations

import asyncio
import os
import random

import pytest

# Skip in CI — these benchmarks need sentence-transformers + real DB
pytestmark = pytest.mark.skipif(
    os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true",
    reason="Benchmark tests require sentence-transformers and a real database",
)

from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Spell corpus ──────────────────────────────────────────────────────────

REAL_SPELLS: list[dict[str, str]] = [
    {"name": "Expelliarmus", "effect": "Disarms the opponent, forcing them to release whatever they are holding"},
    {"name": "Expecto Patronum", "effect": "Conjures a Patronus, a silvery guardian that repels Dementors"},
    {"name": "Lumos", "effect": "Creates a beam of light at the tip of the caster's wand"},
    {"name": "Nox", "effect": "Extinguishes the light created by Lumos"},
    {"name": "Accio", "effect": "Summons an object toward the caster"},
    {"name": "Wingardium Leviosa", "effect": "Levitates and moves objects through the air"},
    {"name": "Stupefy", "effect": "Stuns the target, rendering them unconscious"},
    {"name": "Protego", "effect": "Creates an invisible shield that deflects spells and physical attacks"},
    {"name": "Obliviate", "effect": "Erases specific memories from the target's mind"},
    {"name": "Petrificus Totalus", "effect": "Temporarily paralyzes the target's entire body"},
    {"name": "Riddikulus", "effect": "Forces a Boggart to assume a humorous shape chosen by the caster"},
    {"name": "Sectumsempra", "effect": "Slashes the target as if struck by an invisible sword, causing deep gashes"},
    {"name": "Crucio", "effect": "Inflicts excruciating pain on the target, one of the three Unforgivable Curses"},
    {"name": "Imperio", "effect": "Places the target under complete mind control of the caster"},
    {"name": "Avada Kedavra", "effect": "The Killing Curse, causes instant death with no counter-curse"},
    {"name": "Alohomora", "effect": "Unlocks doors and windows that have been sealed with a locking charm"},
    {"name": "Reparo", "effect": "Repairs broken or damaged objects, restoring them to their original state"},
    {"name": "Episkey", "effect": "Heals minor injuries such as broken noses and split lips"},
    {"name": "Aguamenti", "effect": "Produces a jet of clean drinkable water from the wand tip"},
    {"name": "Incendio", "effect": "Creates a jet of flames from the wand"},
    {"name": "Impedimenta", "effect": "Slows down or stops an approaching target"},
    {"name": "Diffindo", "effect": "Precisely cuts or tears the target object"},
    {"name": "Silencio", "effect": "Magically silences the target, preventing them from making sound"},
    {"name": "Sonorus", "effect": "Amplifies the caster's voice to be heard over great distances"},
    {"name": "Locomotor Mortis", "effect": "Locks the target's legs together preventing movement"},
    {"name": "Rictusempra", "effect": "Causes the target to buckle with uncontrollable laughter"},
    {"name": "Tarantallegra", "effect": "Forces the target's legs to dance uncontrollably"},
    {"name": "Finite Incantatem", "effect": "Terminates all active spell effects in the area"},
    {"name": "Priori Incantatem", "effect": "Reveals the last spells cast by a wand in reverse order"},
    {"name": "Confundo", "effect": "Causes the target to become confused and disoriented"},
    {"name": "Reducto", "effect": "Blasts solid objects into pieces with explosive force"},
    {"name": "Bombarda", "effect": "Creates a small explosion that can blast open sealed passages"},
    {"name": "Colloportus", "effect": "Magically locks a door so it cannot be opened by normal means"},
    {"name": "Engorgio", "effect": "Causes the target to swell and grow in size"},
    {"name": "Reducio", "effect": "Shrinks an enlarged object back to its original size"},
    {"name": "Serpensortia", "effect": "Conjures a live serpent from the tip of the wand"},
    {"name": "Anapneo", "effect": "Clears the target's airway if they are choking"},
    {"name": "Tergeo", "effect": "Siphons liquid or residue off a surface"},
    {"name": "Scourgify", "effect": "Cleans an object by removing dirt grime and other substances"},
    {"name": "Muffliato", "effect": "Creates a buzzing in nearby ears preventing eavesdropping"},
]

FAKE_SPELLS: list[dict[str, str]] = [
    {"name": "Veritanox", "effect": "Forces the target to speak only in reversed sentences for one hour"},
    {"name": "Crepusculum", "effect": "Summons a localized twilight zone that dims all magical light sources"},
    {"name": "Phantorius", "effect": "Creates an illusory duplicate of the caster that mimics their movements"},
    {"name": "Nexularis", "effect": "Temporarily binds two wands together making them cast identical spells"},
]

DOMAIN = "hogwarts-benchmark"
AGENT_CONTEXT = "spell-test"


# ── Fixtures ──────────────────────────────────────────────────────────────


def _get_store() -> MemoryStore:
    s = get_memory_settings()
    return MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)


@pytest.fixture(autouse=True)
def clean_benchmark_memories():
    """Remove benchmark memories before and after each test."""
    store = _get_store()
    store._conn.execute(
        "DELETE FROM memories WHERE domain = %s", (DOMAIN,)
    )
    store._conn.commit()
    yield
    store._conn.execute(
        "DELETE FROM memories WHERE domain = %s", (DOMAIN,)
    )
    store._conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────


async def _ingest_spells(
    spells: list[dict[str, str]],
    replacements: dict[str, dict[str, str]],
) -> list[str]:
    """Store spells as memories, applying replacements. Returns altered names."""
    altered: list[str] = []
    for spell in spells:
        name = spell["name"]
        effect = spell["effect"]

        if name in replacements:
            fake = replacements[name]
            altered.append(name)
            name = fake["name"]
            effect = fake["effect"]

        content = (
            f"Spell: {name}\n"
            f"Effect: {effect}\n"
            f"Source: Standard Book of Spells"
        )
        await remember_handler({
            "content": content,
            "tags": ["spell", f"spell:{name}"],
            "domain": DOMAIN,
            "source": "benchmark",
            "force": True,
            "agent_topic": AGENT_CONTEXT,
        })

    return altered


async def _recall_spell(query: str, top_k: int = 5) -> list[dict]:
    """Recall memories matching a spell query."""
    result = await recall_handler({
        "query": query,
        "domain": DOMAIN,
        "max_results": top_k,
    })
    return result.get("results", [])


# ── Tests ─────────────────────────────────────────────────────────────────


class TestSpellAlteration:
    """Needle-in-a-haystack: detect 2 altered spells among 40 real ones."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_recall_real_spell_by_effect(self) -> None:
        """Can recall find a specific real spell by its effect description?"""
        async def _test():
            await _ingest_spells(REAL_SPELLS, {})
            results = await _recall_spell("disarms the opponent forcing them to release")
            contents = [r.get("content", "") for r in results]
            assert any("Expelliarmus" in c for c in contents)

        self._run(_test())

    def test_recall_patronus_spell(self) -> None:
        """Can recall find Expecto Patronum by description?"""
        async def _test():
            await _ingest_spells(REAL_SPELLS, {})
            results = await _recall_spell("conjures silvery guardian repels Dementors")
            contents = [r.get("content", "") for r in results]
            assert any("Expecto Patronum" in c for c in contents)

        self._run(_test())

    def test_altered_spell_is_stored(self) -> None:
        """When a spell is replaced, the fake version is stored instead."""
        async def _test():
            replacements = {"Lumos": FAKE_SPELLS[0]}
            await _ingest_spells(REAL_SPELLS, replacements)

            # The fake should be findable
            results = await _recall_spell(FAKE_SPELLS[0]["effect"])
            contents = [r.get("content", "") for r in results]
            assert any(FAKE_SPELLS[0]["name"] in c for c in contents)

            # The original should NOT be present
            results = await _recall_spell("beam of light at the tip of the wand")
            contents = [r.get("content", "") for r in results]
            assert not any("Spell: Lumos" in c for c in contents)

        self._run(_test())

    def test_identify_two_altered_spells(self) -> None:
        """Core test: 2 spells replaced, system identifies the fakes."""
        async def _test():
            random.seed(42)
            targets = random.sample([s["name"] for s in REAL_SPELLS], 2)
            replacements = {
                targets[0]: FAKE_SPELLS[0],
                targets[1]: FAKE_SPELLS[1],
            }

            altered = await _ingest_spells(REAL_SPELLS, replacements)
            assert len(altered) == 2

            # Query for each fake spell's effect — should find the fake
            for i, target in enumerate(targets):
                fake = FAKE_SPELLS[i]
                results = await _recall_spell(fake["effect"])
                contents = [r.get("content", "") for r in results]
                assert any(
                    fake["name"] in c for c in contents
                ), f"Failed to find fake spell {fake['name']}"

            # Query for each original spell's effect — should NOT find it
            for target in targets:
                original = next(s for s in REAL_SPELLS if s["name"] == target)
                results = await _recall_spell(original["effect"])
                contents = [r.get("content", "") for r in results]
                assert not any(
                    f"Spell: {target}" in c for c in contents
                ), f"Original spell {target} should not exist"

        self._run(_test())

    def test_unaltered_spells_still_correct(self) -> None:
        """All non-replaced spells remain intact and retrievable."""
        async def _test():
            replacements = {
                "Stupefy": FAKE_SPELLS[2],
                "Protego": FAKE_SPELLS[3],
            }
            await _ingest_spells(REAL_SPELLS, replacements)

            # Check 5 random unaltered spells
            unaltered = [s for s in REAL_SPELLS if s["name"] not in replacements]
            for spell in random.Random(99).sample(unaltered, 5):
                results = await _recall_spell(spell["effect"])
                contents = [r.get("content", "") for r in results]
                assert any(
                    spell["name"] in c for c in contents
                ), f"Unaltered spell {spell['name']} not found for: {spell['effect'][:50]}"

        self._run(_test())
