from src.retrieval.bm25 import BM25Retriever

def test_bm25_retriever():
    retriever = BM25Retriever()
    chunks = [
        {"text": "The quick brown fox jumps over the lazy dog", "metadata": {"id": "1"}},
        {"text": "A fast brown fox", "metadata": {"id": "2"}}
    ]
    
    retriever.fit(chunks)
    results = retriever.retrieve("quick brown fox", top_k=1)
    
    assert len(results) == 1
    assert "quick" in results[0]["text"]


def test_single_document_and_punctuation():
    retriever = BM25Retriever()
    retriever.fit([{"text": "RAG uses retrieval.", "metadata": {"source": "one.txt", "chunk_index": 0}}])
    assert retriever.retrieve("RAG?")[0]["metadata"]["source"] == "one.txt"
    assert retriever.retrieve("unrelated") == []
    assert retriever.retrieve("RAG", top_k=0) == []


def test_empty_corpus_and_empty_chunks():
    retriever = BM25Retriever()
    retriever.fit([{"text": "  ", "metadata": {}}])
    assert retriever.retrieve("query") == []


def test_sparse_json_round_trip_and_corrupt_file(tmp_path):
    path = tmp_path / "index.json"
    retriever = BM25Retriever()
    retriever.fit([{"id": "stable-id", "text": "persistent evidence", "metadata": {"source": "one.txt"}}])
    retriever.save(str(path))
    restored = BM25Retriever()
    assert restored.load(str(path))
    assert restored.retrieve("evidence")[0]["id"] == "stable-id"
    path.write_text("not json", encoding="utf-8")
    assert not restored.load(str(path))
    assert not restored.load(str(tmp_path / "unsafe.pkl"))
