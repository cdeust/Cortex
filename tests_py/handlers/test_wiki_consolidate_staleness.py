"""Tests for ADR-0051 STEP 4 — wiki_consolidate Pass 2 reference-link
persistence (mcp_server.handlers.wiki_consolidate_staleness).

Covers:
  1. dry_run guard — zero DB writes (no apply_staleness_decisions, no
     insert_memo, no upsert_page_sources) when dry_run=True.
  2. references_written / staleness summary shape when not dry_run.
  3. references land normalized + with correct per-path origin end to end
     (harvest -> normalize -> persist), via the actual upsert call args.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from mcp_server.handlers.wiki_consolidate_staleness import run_staleness_pass
from tests_py._store_call import FakeConnStore, mark_test_operation


def _operation_mock() -> MagicMock:
    """A mock standing in for a marked store operation (ADR-1112
    increment 2): ``store.call`` passes it the borrowed connection first."""
    return mark_test_operation(MagicMock())


def _page(page_id: int, *, lead: str = "", is_stale: bool = False) -> dict:
    return {"id": page_id, "lead": lead, "sections": {}, "is_stale": is_stale}


@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.upsert_page_sources",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.insert_memo",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.apply_staleness_decisions",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.get_claim_file_refs_for_pages",
    new_callable=_operation_mock,
)
def test_dry_run_performs_zero_writes(
    mock_claims, mock_apply, mock_memo, mock_upsert
) -> None:
    mock_claims.return_value = {1: ["mcp_server/core/a.py"]}
    pages = [_page(1, lead="mcp_server/core/a.py cited")]

    summary = run_staleness_pass(
        FakeConnStore(), pages=pages, repo_root=Path("/tmp/nonexistent"), dry_run=True
    )

    mock_apply.assert_not_called()
    mock_memo.assert_not_called()
    mock_upsert.assert_not_called()
    assert summary["transitions_written"] == 0
    assert summary["references_written"] == 0
    assert summary["skipped"] is False


@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.upsert_page_sources",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.insert_memo",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.apply_staleness_decisions",
    new_callable=_operation_mock,
)
@patch(
    "mcp_server.handlers.wiki_consolidate_staleness.get_claim_file_refs_for_pages",
    new_callable=_operation_mock,
)
def test_not_dry_run_persists_references_per_page(
    mock_claims, mock_apply, mock_memo, mock_upsert
) -> None:
    mock_claims.return_value = {1: ["mcp_server/core/a.py"]}
    mock_apply.return_value = 0
    mock_upsert.return_value = 1
    pages = [_page(1, lead="mcp_server/core/a.py and mcp_server/core/b.py cited")]

    summary = run_staleness_pass(
        FakeConnStore(), pages=pages, repo_root=Path("/tmp/nonexistent"), dry_run=False
    )

    mock_apply.assert_called_once()
    mock_upsert.assert_called_once()
    call_args = mock_upsert.call_args
    assert call_args.kwargs["link_kind"] == "references"
    entries = dict(call_args.args[2])
    assert entries["mcp_server/core/a.py"] == "claim_evidence"
    assert entries["mcp_server/core/b.py"] == "body"
    assert summary["references_written"] == 1
