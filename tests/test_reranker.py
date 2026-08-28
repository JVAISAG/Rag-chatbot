from unittest.mock import MagicMock
from src.retrieval.reranker import CrossEncoderReranker

def test_reranker():
    # Mock the CrossEncoder model
    mock_model = MagicMock()
    mock_model.predict.return_value = [0.9, 0.1, 0.5]
    
    reranker = CrossEncoderReranker(model=mock_model)
    
    candidates = [
        {"text": "Bad match"},
        {"text": "Worst match"},
        {"text": "Okay match"}
    ]
    
    # 0.9 -> index 0, 0.5 -> index 2, 0.1 -> index 1
    results = reranker.rerank("query", candidates, top_k=2)
    
    assert len(results) == 2
    assert results[0]["text"] == "Bad match" # It got 0.9 score
    assert results[1]["text"] == "Okay match" # It got 0.5 score
    assert results[0]["score"] == 0.9
