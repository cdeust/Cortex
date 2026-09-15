"""Cardinality and failure contracts with fake IO; no production model or DB."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from benchmarks.reranker_matrix.entry import resolve_script
from benchmarks.reranker_matrix.handler_probe import probe
from benchmarks.reranker_matrix.matrix import CELLS, commands, execute
from benchmarks.reranker_matrix.runtime import fetched, reranked
from mcp_server.shared.telemetry_context import count_reranked


def test_prefix_changes_only_candidate_count_not_sql_parameters():
    ctx = SimpleNamespace(top_k=10)
    weights = {"vector": 1.0}
    rows = [{"memory_id": i, "score": i} for i in range(30)]
    calls = []

    def original(context, coefficients):
        calls.append((context, coefficients))
        return rows

    baseline = fetched(original, 3, [])(ctx, weights)
    reduced = fetched(original, 2, [])(ctx, weights)
    assert baseline == rows and reduced == rows[:20]
    assert calls == [(ctx, weights), (ctx, weights)]
    assert len(rows) == 30


def test_reranker_records_real_success_and_fails_on_silent_skip():
    stats = []

    def success(query, candidates, content_lookup, **kwargs):
        count_reranked(len(candidates))
        return candidates

    rows = [(1, 0.5), (2, 0.4)]
    assert reranked(success, stats)("q", rows, {}) == rows
    assert stats[0]["reranked_count"] == len(rows)
    assert stats[0]["wall_ns"] > 0 and stats[0]["cpu_ns"] > 0
    with pytest.raises(RuntimeError, match="skipped/failed"):
        reranked(lambda *args: rows, [])("q", rows, {})


@pytest.mark.parametrize("multiplier", [2, 3])
@pytest.mark.parametrize("include_low_signal", [False, True])
def test_real_handler_function_bodies_expose_90_vs_30(multiplier, include_low_signal):
    result = probe(multiplier, 10, include_low_signal)
    pg_k = 10 if include_low_signal else 30
    assert result["sql_max_results"] == pg_k
    assert result["sql_returned"] == pg_k * 3
    assert result["rerank_candidates"] == pg_k * multiplier
    assert result["pre_enrichment_count"] == 10
    if not include_low_signal:
        assert result["handler_before_filter"] == 30
        assert result["handler_after_filter"] == 15


def test_matrix_commands_differ_only_by_cell_and_output(tmp_path):
    planned = commands(tmp_path)
    assert len(planned) == 4
    assert [argv[4] for argv in planned] == list(CELLS)
    assert all(
        argv[:4]
        == ["bash", "benchmarks/reproduce.sh", "--no-ablation", "--reranker-cell"]
        for argv in planned
    )
    assert all("--quick" not in argv and "--limit" not in argv for argv in planned)


def test_matrix_retains_all_four_failures_and_runs_sequentially(tmp_path):
    with (
        patch("benchmarks.reranker_matrix.matrix.verify"),
        patch("benchmarks.reranker_matrix.matrix.durable_root", return_value=tmp_path),
        patch("benchmarks.reranker_matrix.matrix.subprocess.run") as run,
    ):
        run.return_value.returncode = 1
        result = execute(tmp_path / "results")
    assert run.call_count == 4
    assert list(result["results"]) == list(CELLS)
    assert all(row["returncode"] == 1 for row in result["results"].values())
    environments = [call.kwargs["env"] for call in run.call_args_list]
    assert all(env == environments[0] for env in environments)
    assert (tmp_path / "results/matrix.json").is_file()


def test_entry_rejects_unrelated_or_production_script():
    with pytest.raises(ValueError, match="only reproduce"):
        resolve_script(str(Path("mcp_server/server.py")))


def fake_modules():
    from mcp_server.core import reranker_model

    ranker = SimpleNamespace(
        _MODEL_NAME=reranker_model._MODEL_NAME,
        _MODEL_FILE=reranker_model._MODEL_FILE,
        reranker_cache_dir=reranker_model.reranker_cache_dir,
        reranker_status=lambda: SimpleNamespace(state="not_attempted"),
        _flashrank_instance=None,
        _flashrank_failed=False,
        _flashrank_load_error=None,
        silent_failure=SimpleNamespace(note=lambda *args: None),
    )
    return {
        "mcp_server.core.reranker_model": reranker_model,
        "mcp_server.core.reranker": ranker,
        "mcp_server.core.pg_recall_context": SimpleNamespace(_wrrf_fetch=lambda *a: []),
        "mcp_server.core.pg_recall_stages": SimpleNamespace(
            rerank_results=lambda *a: []
        ),
        "benchmarks.beam.data": SimpleNamespace(load_beam_dataset=lambda *a: []),
        "benchmarks.locomo.data": SimpleNamespace(load_locomo=lambda *a: []),
    }


def test_cell_model_cache_and_state_restore_without_changing_defaults(tmp_path):
    from benchmarks.reranker_matrix.pins import cell
    from benchmarks.reranker_matrix.runtime import selected_cell

    modules = fake_modules()
    model = modules["mcp_server.core.reranker_model"]
    ranker = modules["mcp_server.core.reranker"]
    original = model._MODEL_NAME
    with (
        patch("benchmarks.reranker_matrix.runtime.verify", return_value={}),
        patch("benchmarks.reranker_matrix.runtime.durable_root", return_value=tmp_path),
        patch(
            "benchmarks.reranker_matrix.runtime.import_module",
            side_effect=modules.__getitem__,
        ),
    ):
        with selected_cell(cell("l2-2x")):
            assert model._MODEL_NAME == ranker._MODEL_NAME == cell("l2-2x").model.name
            assert model._model_path() == str(
                tmp_path / model._MODEL_NAME / model._MODEL_FILE
            )
            ranker._flashrank_instance = object()
    assert model._MODEL_NAME == ranker._MODEL_NAME == original
    assert ranker._flashrank_instance is None


def test_cache_verification_failure_precedes_any_model_import():
    from benchmarks.reranker_matrix.pins import cell
    from benchmarks.reranker_matrix.runtime import selected_cell

    with (
        patch(
            "benchmarks.reranker_matrix.runtime.verify", side_effect=ValueError("hash")
        ),
        patch("benchmarks.reranker_matrix.runtime.import_module") as imported,
    ):
        with pytest.raises(ValueError, match="hash"), selected_cell(cell("l2-2x")):
            pytest.fail("must not enter cell")
    imported.assert_not_called()


def test_observed_reranker_failure_cannot_become_a_score():
    from benchmarks.reranker_matrix.runtime import reject_failure

    calls = []
    note = reject_failure(lambda *args: calls.append(args))
    error = ValueError("fixture blend failure")
    with pytest.raises(RuntimeError, match="reranker.rerank_call"):
        note("reranker.rerank_call", error)
    assert calls == [("reranker.rerank_call", error)]


def test_matrix_rejects_mixed_sql_or_gate_inputs():
    from copy import deepcopy
    from benchmarks.reranker_matrix.matrix import consistent_inputs

    item = {
        "complete_artifacts": True,
        "results": {
            "MANIFEST.json": {
                "git_sha": "sha",
                "longmemeval_dataset_sha256": "data",
                "embedding_model_revision": "emb",
                "pg_image": "pg",
                "packages": {},
                "python": "3.12",
            },
            "reranker-cell.json": {"code_sha256": {"gate": "same"}, "packages": {}},
        },
    }
    item["results"].update(
        {
            "locomo.reranker-cell.json": {"datasets": {"locomo": {"sha256": "same"}}},
            "beam-100K.reranker-cell.json": {"datasets": {"beam": {"sha256": "same"}}},
        }
    )
    results = {"baseline": item, "candidate": deepcopy(item)}
    assert consistent_inputs(results)
    results["candidate"]["results"]["reranker-cell.json"]["code_sha256"]["gate"] = (
        "changed"
    )
    assert not consistent_inputs(results)


def test_loaded_corpus_fingerprint_preserves_rows_and_detects_data_change():
    from benchmarks.reranker_matrix.corpus import loaded_corpus

    rows = [{"text": "fixture", "id": 1}]
    evidence = {}
    assert loaded_corpus(lambda: rows, "beam", evidence)() is rows
    first = evidence["beam"]
    rows[0]["text"] = "changed fixture"
    loaded_corpus(lambda: rows, "beam", evidence)()
    assert first["sha256"] != evidence["beam"]["sha256"]
    with pytest.raises(TypeError, match="re-iterable"):
        loaded_corpus(lambda: iter(rows), "beam", {})()
