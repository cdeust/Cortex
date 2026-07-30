"""Regression: the four consolidation submodules import standalone (#237).

Before the fix, ``candidate_scan``, ``claude_cli``, ``cycle_orchestration``,
and ``drain_operations`` each did ``from . import headless_authoring as
_root`` at module top, while ``headless_authoring`` imported names back from
each of them at ITS module top. Importing ``headless_authoring`` first
resolved the cycle (which is why the test suite stayed green), but importing
any of the four directly in a fresh interpreter raised:

    ImportError: cannot import name '<name>' from partially initialized
    module '...' (most likely due to a circular import)

Each import below MUST run in its own subprocess — within a single
interpreter, the first successful import populates ``sys.modules`` and
masks the cycle for every subsequent import, exactly the false-green this
regression test exists to prevent (matching issue #233 criterion 1's
subprocess pattern for the same defect class).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_AFFECTED_MODULES = (
    "mcp_server.handlers.consolidation.candidate_scan",
    "mcp_server.handlers.consolidation.claude_cli",
    "mcp_server.handlers.consolidation.cycle_orchestration",
    "mcp_server.handlers.consolidation.drain_operations",
)


@pytest.mark.parametrize("module_name", _AFFECTED_MODULES)
def test_submodule_imports_standalone_in_fresh_interpreter(module_name: str) -> None:
    """Each submodule imports successfully with no prior sibling import.

    Regression for issue #237: pre-fix, this subprocess call exits non-zero
    with the partially-initialized-module ImportError quoted in the module
    docstring above.
    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"import {module_name} failed in a fresh interpreter:\n{result.stderr}"
    )


def test_headless_authoring_still_imports_first_and_re_exports() -> None:
    """The normal (hub-first) import path is unaffected by the fix.

    Runs in-process (not a subprocess): this repo's conftest already
    imported plenty of ``mcp_server`` modules by the time this test runs,
    so this assertion is about the re-export surface, not fresh-interpreter
    import order (that's covered by the parametrized test above).
    """
    from mcp_server.handlers.consolidation import headless_authoring as ha

    assert callable(ha.run_headless_authoring_cycle)
    assert callable(ha._collect_anchor_candidates)
    assert callable(ha._scan_pages_with_gaps)
    assert callable(ha.drain_one)
    assert callable(ha.drain_all_gaps_on_page)
    assert callable(ha.drain_missing_anchors)
    assert callable(ha._build_argv)
    assert callable(ha._subprocess_env)


# ── Sentinel-default resolution (part of the #237 fix, not just the import
# reordering) ────────────────────────────────────────────────────────────
#
# Breaking the load-time cycle required converting the DI-seam parameters
# that used to be baked at function-DEFINITION time (``invoke: ... =
# _root._claude_invoke``, ``max_drains: int = _root.CORTEX_HEADLESS_MAX_
# FILE_DRAINS``) into ``None`` sentinels resolved inside the function body
# instead — ``_root.X`` cannot appear in a parameter-list default when
# ``_root`` is only bound lazily inside the body. These tests pin that the
# sentinel resolution still reads the LIVE ``headless_authoring`` module
# attribute at call time (the same or better patchability than the old
# baked default, which could never observe a monkeypatch applied after
# the sibling module was first imported).


@pytest.mark.asyncio
async def test_drain_one_default_invoke_resolves_to_live_claude_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_server.handlers.consolidation import headless_authoring as ha
    from mcp_server.handlers.consolidation import page_io

    calls: list[str] = []

    async def fake_invoke(prompt: str, **_kw: Any) -> Any:
        calls.append(prompt)
        return ha.InvokeResult(text="filled content", cost_usd=0.0)

    async def fake_write(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ha, "_claude_invoke", fake_invoke)
    monkeypatch.setattr(page_io, "write_governed_page", fake_write)

    page = tmp_path / "p.md"
    page.write_text("_(missing — needs: What)_", encoding="utf-8")
    meta = {
        "curation_gaps": ["purpose"],
        "domain": "d",
        "kind": "reference",
        "source_file_path": "x.py",
    }

    # No `invoke=` kwarg: must resolve to the live ha._claude_invoke, not
    # crash with AttributeError/NameError and not silently no-op. Whether
    # the fill itself parses into "filled" is prompt-format detail this
    # test doesn't care about — the sentinel-resolution contract is that
    # `invoke` gets CALLED at all when omitted.
    await ha.drain_one(page, meta, "_(missing — needs: What)_", wiki_root=tmp_path)

    assert calls, "omitting `invoke` must still call the live _claude_invoke"


@pytest.mark.asyncio
async def test_drain_all_gaps_on_page_default_invoke_resolves_to_live_claude_invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_server.handlers.consolidation import headless_authoring as ha
    from mcp_server.handlers.consolidation import page_io

    calls: list[str] = []

    async def fake_invoke(prompt: str, **_kw: Any) -> Any:
        calls.append(prompt)
        return ha.InvokeResult(text="PURPOSE:\nfilled content\n", cost_usd=0.0)

    async def fake_write(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(ha, "_claude_invoke", fake_invoke)
    monkeypatch.setattr(page_io, "write_governed_page", fake_write)

    page = tmp_path / "p.md"
    page.write_text("_(missing — needs: What)_", encoding="utf-8")
    meta = {
        "curation_gaps": ["purpose"],
        "domain": "d",
        "kind": "reference",
        "source_file_path": "x.py",
    }

    results = await ha.drain_all_gaps_on_page(
        page, meta, "_(missing — needs: What)_", wiki_root=tmp_path
    )

    # As above, only the sentinel-resolution contract (invoke gets called)
    # is under test here — not the prompt/response parsing format.
    assert calls, "omitting `invoke` must still call the live _claude_invoke"
    assert results, "a page with a live gap must produce at least one result"


@pytest.mark.asyncio
async def test_run_headless_authoring_cycle_defaults_resolve_from_live_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting ``invoke``/``max_drains``/``max_anchor_drains`` must resolve
    them from the live ``headless_authoring`` attributes — this is the
    production call shape (``wiki_maintenance.run_headless_authoring_cycle()``
    with no arguments).

    Pins the CAP itself, not just that a value got resolved: 3 file-doc
    candidates and 3 anchor candidates are offered, ``CORTEX_HEADLESS_MAX_
    FILE_DRAINS``/``..._MAX_ANCHOR_DRAINS`` are patched to 1 each, and only
    1-of-3 must be processed on each side when the caller omits both caps
    — a single spare candidate would let a broken sentinel (e.g. mutating
    ``if max_drains is None`` to ``is not None``, which leaves the sentinel
    unresolved at ``None`` and ``list[:None]`` silently means "no cap") slip
    through undetected (mutation run, 2026-07-30: this exact mutant
    survived a 1-candidate version of this test).
    """
    from mcp_server.handlers.consolidation import headless_authoring as ha

    calls: list[str] = []

    async def fake_invoke(prompt: str, **_kw: Any) -> Any:
        calls.append(prompt)
        return ha.InvokeResult(text="content", cost_usd=0.0)

    monkeypatch.setattr(ha, "_claude_invoke", fake_invoke)
    monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_FILE_DRAINS", 1)
    monkeypatch.setattr(ha, "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS", 1)

    anchor_max_drains_seen: list[int | None] = []

    def fake_collect(_wiki_root: Path, max_drains: int | None) -> list[Any]:
        anchor_max_drains_seen.append(max_drains)
        return [
            ha._AnchorCandidate(
                domain="proj",
                scope_name=f"scope_{i}",
                scope_title=f"Scope {i}",
                scope_description=f"Description {i}",
                source_root=str(tmp_path),
                suggested_path=f"reference/proj/scope_{i}.md",
                suggested_kind="reference",
            )
            for i in range(3)
        ][: max_drains if max_drains is not None else 3]

    monkeypatch.setattr(ha, "_collect_anchor_candidates", fake_collect)

    def fake_scan(_wiki_root: Path) -> list[Any]:
        pages = []
        for i in range(3):
            page = tmp_path / f"p{i}.md"
            page.write_text("_(missing — needs: What)_", encoding="utf-8")
            pages.append(
                (
                    page,
                    {
                        "curation_gaps": ["purpose"],
                        "domain": "d",
                        "kind": "reference",
                        "source_file_path": "x.py",
                    },
                    "_(missing — needs: What)_",
                )
            )
        return pages

    monkeypatch.setattr(ha, "_scan_pages_with_gaps", fake_scan)

    from mcp_server.handlers.consolidation import page_io

    async def fake_write(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(page_io, "write_governed_page", fake_write)

    # No `invoke=`, no `max_drains=`, no `max_anchor_drains=` — the exact
    # shape wiki_maintenance.py's production call uses.
    summary = await ha.run_headless_authoring_cycle(tmp_path)

    assert calls, "omitted invoke must resolve to the live _claude_invoke"
    assert anchor_max_drains_seen == [1], (
        "omitted max_anchor_drains must resolve to the live "
        "CORTEX_HEADLESS_MAX_ANCHOR_DRAINS (1), not stay unresolved at None"
    )
    assert summary.pages_scanned == 3
    assert summary.pages_with_gaps == 1, (
        "omitted max_drains must cap file-doc candidates at the live "
        "CORTEX_HEADLESS_MAX_FILE_DRAINS (1), not silently process all 3"
    )
