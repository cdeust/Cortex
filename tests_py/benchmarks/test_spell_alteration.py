"""Spell alteration benchmark — needle-in-a-haystack memory fidelity test.

Ingests Harry Potter spell knowledge (40 spells with descriptions),
replaces exactly 2 real spells with fake alternatives, stores everything
as memories, then tests whether the system can:
  1. Retrieve the correct spell when queried by name
  2. Confirm altered originals no longer exist in the store
  3. Verify unaltered spells remain intact

Tests use exact name queries and direct store lookups — works with any
embedding backend (semantic or hash fallback).
"""

from __future__ import annotations

import asyncio
import random

import pytest

from mcp_server.handlers.recall import handler as recall_handler
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Spell corpus ──────────────────────────────────────────────────────────

REAL_SPELLS: list[dict[str, str]] = [
    {"name": "Expelliarmus", "effect": "Disarms the opponent"},
    {"name": "Expecto Patronum", "effect": "Conjures a silvery Patronus"},
    {"name": "Lumos", "effect": "Creates light at the wand tip"},
    {"name": "Nox", "effect": "Extinguishes light from Lumos"},
    {"name": "Accio", "effect": "Summons an object toward the caster"},
    {"name": "Wingardium Leviosa", "effect": "Levitates objects"},
    {"name": "Stupefy", "effect": "Stuns the target unconscious"},
    {"name": "Protego", "effect": "Creates an invisible shield"},
    {"name": "Obliviate", "effect": "Erases specific memories"},
    {"name": "Petrificus Totalus", "effect": "Paralyzes the entire body"},
    {"name": "Riddikulus", "effect": "Turns a Boggart humorous"},
    {"name": "Sectumsempra", "effect": "Slashes with invisible sword"},
    {"name": "Crucio", "effect": "Inflicts excruciating pain"},
    {"name": "Imperio", "effect": "Places target under mind control"},
    {"name": "Avada Kedavra", "effect": "The Killing Curse"},
    {"name": "Alohomora", "effect": "Unlocks sealed doors"},
    {"name": "Reparo", "effect": "Repairs broken objects"},
    {"name": "Episkey", "effect": "Heals minor injuries"},
    {"name": "Aguamenti", "effect": "Produces a water jet"},
    {"name": "Incendio", "effect": "Creates flames from the wand"},
    {"name": "Impedimenta", "effect": "Slows approaching targets"},
    {"name": "Diffindo", "effect": "Cuts the target precisely"},
    {"name": "Silencio", "effect": "Magically silences the target"},
    {"name": "Sonorus", "effect": "Amplifies the caster voice"},
    {"name": "Rictusempra", "effect": "Causes uncontrollable laughter"},
    {"name": "Tarantallegra", "effect": "Forces legs to dance"},
    {"name": "Finite Incantatem", "effect": "Terminates active spells"},
    {"name": "Confundo", "effect": "Causes confusion"},
    {"name": "Reducto", "effect": "Blasts objects into pieces"},
    {"name": "Bombarda", "effect": "Creates a small explosion"},
    {"name": "Colloportus", "effect": "Magically locks a door"},
    {"name": "Engorgio", "effect": "Causes target to grow"},
    {"name": "Serpensortia", "effect": "Conjures a live serpent"},
    {"name": "Scourgify", "effect": "Cleans dirt from objects"},
    {"name": "Muffliato", "effect": "Prevents eavesdropping"},
]

FAKE_SPELLS: list[dict[str, str]] = [
    {"name": "Veritanox", "effect": "Forces reversed speech"},
    {"name": "Crepusculum", "effect": "Summons localized twilight"},
    {"name": "Phantorius", "effect": "Creates illusory duplicate"},
    {"name": "Nexularis", "effect": "Binds two wands together"},
]

DOMAIN = "hogwarts-benchmark"


# ── Fixtures ──────────────────────────────────────────────────────────────


def _get_store() -> MemoryStore:
    s = get_memory_settings()
    return MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)


@pytest.fixture(autouse=True)
def clean_benchmark_memories():
    """Remove benchmark memories before and after each test."""
    store = _get_store()
    store._conn.execute("DELETE FROM memories WHERE domain = %s", (DOMAIN,))
    store._conn.commit()
    yield
    store._conn.execute("DELETE FROM memories WHERE domain = %s", (DOMAIN,))
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

        content = f"Spell: {name}\nEffect: {effect}\nSource: Standard Book of Spells"
        await remember_handler(
            {
                "content": content,
                "tags": ["spell", f"spell:{name}"],
                "domain": DOMAIN,
                "source": "benchmark",
                "force": True,
            }
        )

    return altered


def _query_store_for_spell(store: MemoryStore, spell_name: str) -> list[dict]:
    """Direct store query — find memories containing a spell name."""
    rows = store._conn.execute(
        "SELECT id, content FROM memories WHERE domain = %s AND content LIKE %s",
        (DOMAIN, f"%Spell: {spell_name}%"),
    ).fetchall()
    return [dict(r) for r in rows]


async def _recall_by_name(spell_name: str, top_k: int = 5) -> list[dict]:
    """Recall using the exact spell name — works with any embedding backend."""
    result = await recall_handler(
        {
            "query": f"Spell: {spell_name}",
            "domain": DOMAIN,
            "max_results": top_k,
        }
    )
    return result.get("results", [])


# ── Tests ─────────────────────────────────────────────────────────────────


class TestSpellAlteration:
    """Memory fidelity: detect 2 altered spells among 35 real ones."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_all_spells_stored(self) -> None:
        """All 35 spells are stored as individual memories."""

        async def _test():
            await _ingest_spells(REAL_SPELLS, {})
            store = _get_store()
            count = store._conn.execute(
                "SELECT COUNT(*) as c FROM memories WHERE domain = %s",
                (DOMAIN,),
            ).fetchone()
            assert count["c"] == len(REAL_SPELLS)

        self._run(_test())

    def test_recall_real_spell_by_name(self) -> None:
        """Recall finds Expelliarmus when queried by exact name."""

        async def _test():
            await _ingest_spells(REAL_SPELLS, {})
            results = await _recall_by_name("Expelliarmus")
            contents = [r.get("content", "") for r in results]
            assert any("Expelliarmus" in c for c in contents)

        self._run(_test())

    def test_altered_spell_replaces_original_in_store(self) -> None:
        """When Lumos is replaced by Veritanox, only Veritanox is in the store."""

        async def _test():
            replacements = {"Lumos": FAKE_SPELLS[0]}
            await _ingest_spells(REAL_SPELLS, replacements)

            store = _get_store()
            # Fake present
            fake_rows = _query_store_for_spell(store, "Veritanox")
            assert len(fake_rows) == 1

            # Original gone
            orig_rows = _query_store_for_spell(store, "Lumos")
            assert len(orig_rows) == 0

        self._run(_test())

    def test_identify_two_altered_spells(self) -> None:
        """2 spells replaced: fakes exist in store, originals do not."""

        async def _test():
            rng = random.Random(42)
            targets = rng.sample([s["name"] for s in REAL_SPELLS], 2)
            replacements = {
                targets[0]: FAKE_SPELLS[0],
                targets[1]: FAKE_SPELLS[1],
            }

            altered = await _ingest_spells(REAL_SPELLS, replacements)
            assert len(altered) == 2

            store = _get_store()

            # Each fake is stored
            for i, target in enumerate(targets):
                fake = FAKE_SPELLS[i]
                fake_rows = _query_store_for_spell(store, fake["name"])
                assert len(fake_rows) == 1, f"Fake {fake['name']} not found"

            # Each original is gone
            for target in targets:
                orig_rows = _query_store_for_spell(store, target)
                assert len(orig_rows) == 0, f"Original {target} should not exist"

        self._run(_test())

    def test_unaltered_spells_still_correct(self) -> None:
        """All non-replaced spells remain intact in the store."""

        async def _test():
            replacements = {
                "Stupefy": FAKE_SPELLS[2],
                "Protego": FAKE_SPELLS[3],
            }
            await _ingest_spells(REAL_SPELLS, replacements)

            store = _get_store()
            unaltered = [s for s in REAL_SPELLS if s["name"] not in replacements]
            for spell in random.Random(99).sample(unaltered, 5):
                rows = _query_store_for_spell(store, spell["name"])
                assert len(rows) == 1, (
                    f"Unaltered spell {spell['name']} not found in store"
                )

        self._run(_test())

    def test_recall_finds_fake_not_original(self) -> None:
        """Recall for the fake name returns the fake, not the original."""

        async def _test():
            replacements = {"Accio": FAKE_SPELLS[0]}
            await _ingest_spells(REAL_SPELLS, replacements)

            results = await _recall_by_name("Veritanox")
            contents = [r.get("content", "") for r in results]
            assert any("Veritanox" in c for c in contents)

            results = await _recall_by_name("Accio")
            contents = [r.get("content", "") for r in results]
            assert not any("Spell: Accio" in c for c in contents)

        self._run(_test())

    def test_total_memory_count_unchanged(self) -> None:
        """Replacing 2 spells doesn't change total count — still 35."""

        async def _test():
            replacements = {
                "Crucio": FAKE_SPELLS[0],
                "Imperio": FAKE_SPELLS[1],
            }
            await _ingest_spells(REAL_SPELLS, replacements)

            store = _get_store()
            count = store._conn.execute(
                "SELECT COUNT(*) as c FROM memories WHERE domain = %s",
                (DOMAIN,),
            ).fetchone()
            assert count["c"] == len(REAL_SPELLS)

        self._run(_test())
