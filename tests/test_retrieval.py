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
