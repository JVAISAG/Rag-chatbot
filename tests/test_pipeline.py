from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.errors import DocumentError
from src.pipeline import RAGPipeline
from src.retrieval.hybrid import HybridRetriever


def write_document(rag, stored_name, text):
    path = Path(rag.data_dir) / stored_name
    path.write_text(text, encoding="utf-8")
    return path


def test_ingestion_is_incremental(rag):
    first = write_document(rag, "first.txt", "first unique evidence")
    rag.ingest_file(str(first), "first.txt")
    rag.embedding_model.encoded.clear()
    second = write_document(rag, "second.txt", "second distinct evidence")
    rag.ingest_file(str(second), "second.txt")
    assert rag.embedding_model.encoded == ["second distinct evidence"]
    assert len(rag.list_files()) == 2


def test_repeated_upload_does_not_embed_or_duplicate(rag):
    first = write_document(rag, "stored.txt", "same evidence")
    rag.ingest_file(str(first), "display.txt")
    rag.embedding_model.encoded.clear()
    duplicate = write_document(rag, "duplicate.txt", "same evidence")
    rag.ingest_file(str(duplicate), "display.txt")
    assert not duplicate.exists()
    assert first.exists()
    assert rag.embedding_model.encoded == []
    assert rag.list_files() == [{"name": "display.txt", "chunks": 1}]


def test_shorter_replacement_removes_stale_chunks_and_old_saved_file(rag):
    first = write_document(rag, "first.txt", "Long old evidence. " * 500)
    rag.ingest_file(str(first), "display.txt")
    assert len(rag.store.get_all_chunks()) > 1
    replacement = write_document(rag, "replacement.txt", "new evidence")
    rag.ingest_file(str(replacement), "display.txt")
    assert not first.exists()
    assert rag.store.get_all_chunks()[0]["text"] == "new evidence"
    assert len(rag.store.get_all_chunks()) == 1
    rag.build_index()
    assert rag.list_files() == [{"name": "display.txt", "chunks": 1}]


def test_deletion_does_not_return_after_rebuild(rag):
    path = write_document(rag, "stored.txt", "deletion evidence")
    rag.ingest_file(str(path), "original.txt")
    assert rag.remove_file("original.txt")
    assert not path.exists()
    assert rag.sparse_retriever.retrieve("deletion") == []
    assert rag.build_index()
    assert rag.store.get_all_chunks() == []
    assert not rag.remove_file("missing.txt")


def test_sparse_index_is_restored_from_vector_store(pipeline_factory):
    first = pipeline_factory()
    path = write_document(first, "stored.txt", "persistent specialkeyword")
    first.ingest_file(str(path), "original.txt")
    second = pipeline_factory()
    assert second.sparse_retriever.retrieve("specialkeyword")[0]["metadata"]["source"] == "original.txt"


def test_rebuild_removes_documents_deleted_outside_the_app(rag):
    path = write_document(rag, "stored.txt", "old evidence")
    rag.build_index()
    path.unlink()
    assert rag.build_index()
    assert rag.list_files() == []
    assert rag.sparse_retriever.retrieve("evidence") == []


def test_corrupt_document_does_not_destroy_previous_index(rag):
    path = write_document(rag, "stored.txt", "existing evidence")
    rag.build_index()
    before = rag.store.get_all_chunks()
    corrupt = Path(rag.data_dir) / "corrupt.pdf"
    corrupt.write_bytes(b"not a pdf")
    with pytest.raises(DocumentError):
        rag.build_index()
    assert rag.store.get_all_chunks() == before


def test_failed_delete_restores_saved_file(rag, monkeypatch):
    path = write_document(rag, "stored.txt", "existing evidence")
    rag.ingest_file(str(path), "display.txt")
    monkeypatch.setattr(rag.store, "delete_by_source", MagicMock(side_effect=RuntimeError("write failed")))
    with pytest.raises(RuntimeError):
        rag.remove_file("display.txt")
    assert path.read_text(encoding="utf-8") == "existing evidence"
    assert len(rag.list_files()) == 1
    assert not list(Path(rag.data_dir).glob("*.pending-delete"))


def test_failed_replacement_restores_old_file(rag, monkeypatch):
    original = write_document(rag, "stored.txt", "old evidence")
    rag.ingest_file(str(original), "display.txt")
    replacement = write_document(rag, "replacement.txt", "new evidence")
    monkeypatch.setattr(rag.store, "replace_chunks", MagicMock(side_effect=RuntimeError("write failed")))
    with pytest.raises(RuntimeError):
        rag.ingest_file(str(replacement), "display.txt")
    assert original.exists()
    assert rag.sparse_retriever.retrieve("old")


def test_paths_outside_data_directory_are_never_deleted(rag, tmp_path):
    external = tmp_path / "external.txt"
    external.write_text("outside data", encoding="utf-8")
    rag.store.upsert_chunks([
        {"text": "outside data", "metadata": {"source": "outside.txt", "filepath": str(external), "chunk_index": 0}}
    ], np.ones((1, 16)))
    with pytest.raises(DocumentError):
        rag.remove_file("outside.txt")
    assert external.exists()


def test_reranking_works_without_hybrid_search(rag):
    rag.dense_retriever = MagicMock()
    rag.dense_retriever.retrieve.return_value = [{"text": "evidence"}]
    rag.reranker = MagicMock()
    rag.reranker.rerank.return_value = [{"text": "reranked"}]
    rag.query("question", use_reranking=True)
    rag.reranker.rerank.assert_called_once()
    assert rag.llm_generator.generate_answer.call_args.args[1] == [{"text": "reranked"}]


def test_hybrid_flags_do_not_mutate_shared_reranker():
    dense, sparse, reranker = MagicMock(), MagicMock(), MagicMock()
    dense.retrieve.return_value = [{"id": "a", "text": "evidence"}]
    sparse.retrieve.return_value = []
    hybrid = HybridRetriever(dense, sparse, reranker)
    hybrid.retrieve("query", use_reranking=False)
    reranker.rerank.assert_not_called()
    assert hybrid.reranker is reranker
    hybrid.retrieve("query", use_reranking=True)
    reranker.rerank.assert_called_once()


def test_store_rolls_back_a_failed_write(rag, monkeypatch):
    path = write_document(rag, "stored.txt", "old evidence")
    rag.ingest_file(str(path), "display.txt")
    before = rag.store.get_all_chunks()
    original = rag.store._upsert_payload
    calls = 0

    def fail_once(payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated storage failure")
        return original(payload)

    monkeypatch.setattr(rag.store, "_upsert_payload", fail_once)
    with pytest.raises(RuntimeError):
        rag.store.replace_chunks([
            {"text": "new evidence", "metadata": {"source": "display.txt", "chunk_index": 0}}
        ], np.ones((1, 16)), source="display.txt")
    assert rag.store.get_all_chunks() == before


def test_empty_dense_store_does_not_query_chroma(rag):
    assert rag.store.dense_search(np.ones(16), top_k=10) == []


def test_ingestion_uses_embedding_tokenizer_limit(rag):
    rag.embedding_model.max_seq_length = 32
    rag.embedding_model.tokenizer = MagicMock()
    rag.embedding_model.tokenizer.encode.side_effect = lambda text, **kwargs: list(text) + [0, 0]
    path = write_document(rag, "long.txt", "a long paragraph with no sentence boundary " * 20)
    rag.ingest_file(str(path), "long.txt")
    assert all(len(text) + 2 <= 32 for text in rag.embedding_model.encoded)


def test_parallel_uploads_keep_both_sparse_corpora(rag):
    from concurrent.futures import ThreadPoolExecutor

    first = write_document(rag, "one.txt", "firstkeyword evidence")
    second = write_document(rag, "two.txt", "secondkeyword evidence")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda path: rag.ingest_file(str(path), path.name), [first, second]))
    assert results == [True, True]
    assert rag.sparse_retriever.retrieve("firstkeyword")
    assert rag.sparse_retriever.retrieve("secondkeyword")


def test_restart_restores_a_file_staged_before_an_uncommitted_delete(pipeline_factory):
    original = pipeline_factory()
    path = write_document(original, "stored.txt", "existing evidence")
    original.ingest_file(str(path), "display.txt")
    original._stage_files({path})
    assert not path.exists()
    original.close()
    restored = pipeline_factory()
    assert path.read_text(encoding="utf-8") == "existing evidence"
    assert restored.list_files()[0]["name"] == "display.txt"


def test_restart_finishes_a_committed_delete(pipeline_factory):
    original = pipeline_factory()
    path = write_document(original, "stored.txt", "existing evidence")
    original.ingest_file(str(path), "display.txt")
    original._stage_files({path})
    original.store.delete_by_source("display.txt")
    original.close()
    restored = pipeline_factory()
    assert restored.list_files() == []
    assert list(Path(restored.data_dir).iterdir()) == []
