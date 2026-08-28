from typing import List, Dict, Any

def reciprocal_rank_fusion(dense_results: List[Dict[str, Any]], sparse_results: List[Dict[str, Any]], k: int = 60) -> List[Dict[str, Any]]:
    """
    Fuse dense and sparse retrieval results using Reciprocal Rank Fusion.
    score = sum(1 / (k + rank))
    """
    fused_scores = {}
    chunk_map = {}
    
    # Process dense
    for rank, item in enumerate(dense_results, start=1):
        doc_id = item["id"]
        chunk_map[doc_id] = item
        fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        
    # Process sparse
    for rank, item in enumerate(sparse_results, start=1):
        doc_id = item["id"]
        if doc_id not in chunk_map:
            chunk_map[doc_id] = item
        fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        
    # Sort by fused score
    sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)
    
    output = []
    for doc_id in sorted_ids:
        item = chunk_map[doc_id].copy()
        item["score"] = fused_scores[doc_id]
        output.append(item)
        
    return output
