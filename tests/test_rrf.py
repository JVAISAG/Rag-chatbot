from src.retrieval.rrf import reciprocal_rank_fusion

def test_rrf():
    dense = [
        {"id": "doc1", "text": "A"},
        {"id": "doc2", "text": "B"}
    ]
    sparse = [
        {"id": "doc2", "text": "B"},
        {"id": "doc3", "text": "C"}
    ]
    
    fused = reciprocal_rank_fusion(dense, sparse, k=60)
    
    assert len(fused) == 3
    # doc2 should be ranked first because it appears in both at high ranks
    assert fused[0]["id"] == "doc2"
    assert "score" in fused[0]
