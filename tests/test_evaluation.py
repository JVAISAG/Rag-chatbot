from unittest.mock import MagicMock

import pytest

from eval.run import calculate_mrr, calculate_ndcg_at_k, calculate_recall_at_k, get_rank_of_expected_source, retrieve, run_evaluation


def test_known_retrieval_metrics():
    assert calculate_mrr([1, 2, 0]) == pytest.approx(0.5)
    assert calculate_recall_at_k([1, 2, 0], 1) == pytest.approx(1 / 3)
    assert calculate_ndcg_at_k([1, 0], 5) == 0.5


def test_expected_source_must_match_exactly():
    assert get_rank_of_expected_source([{"metadata": {"source": "other-report.txt"}}], "report.txt") == 0


def test_naive_hybrid_keeps_remaining_sparse_results():
    pipeline = MagicMock()
    pipeline.dense_retriever.retrieve.return_value = []
    pipeline.sparse_retriever.retrieve.return_value = [{"id": "sparse", "metadata": {"source": "one.txt"}}]
    assert retrieve(pipeline, "query", "hybrid", 3)[0]["id"] == "sparse"


def test_reranking_mode_runs_the_actual_reranker_path():
    pipeline = MagicMock()
    retrieve(pipeline, "query", "hybrid_rrf_rerank", 3)
    pipeline.hybrid_retriever.retrieve.assert_called_once_with("query", top_k=3, use_reranking=True)


def test_metrics_use_requested_k():
    pipeline = MagicMock()
    pipeline.sparse_retriever.retrieve.return_value = [{"metadata": {"source": "one.txt"}}]
    result = run_evaluation([{"question": "query", "expected_source": "one.txt"}], pipeline, "bm25", k=3)
    assert result["Recall@3"] == 1.0
    assert result["MRR@3"] == 1.0


def test_temporary_index_retries_delayed_windows_handle_release(monkeypatch, tmp_path):
    import eval.run as evaluation

    directory = MagicMock()
    directory.name = str(tmp_path / "rag-evaluation-test")
    directory.cleanup.side_effect = [PermissionError("handle still closing"), None]
    monkeypatch.setattr(evaluation.tempfile, "TemporaryDirectory", MagicMock(return_value=directory))
    monkeypatch.setattr(evaluation.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(evaluation.time, "sleep", MagicMock())
    with evaluation.temporary_index() as path:
        assert path == directory.name
    assert directory.cleanup.call_count == 2
