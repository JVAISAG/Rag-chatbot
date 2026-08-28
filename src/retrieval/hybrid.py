from typing import List, Dict, Any
from src.retrieval.base import Retriever
from src.retrieval.dense import DenseRetriever
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.rrf import reciprocal_rank_fusion
from src.retrieval.reranker import CrossEncoderReranker

class HybridRetriever(Retriever):
    def __init__(self, 
                 dense_retriever: DenseRetriever, 
                 sparse_retriever: BM25Retriever, 
                 reranker: CrossEncoderReranker = None):
        self.dense = dense_retriever
        self.sparse = sparse_retriever
        self.reranker = reranker
        
    def retrieve(self, query: str, top_k: int = 10, use_rrf: bool = True) -> List[Dict[str, Any]]:
        """
        Hybrid retrieval combining dense and sparse results.
        If use_rrf is True, uses Reciprocal Rank Fusion.
        Otherwise, returns dense results as primary (naive fallback).
        Applies reranker if configured.
        """
        # Fetch more candidates to allow effective fusion and reranking
        fetch_k = top_k * 2
        
        dense_results = self.dense.retrieve(query, top_k=fetch_k)
        sparse_results = self.sparse.retrieve(query, top_k=fetch_k)
        
        if use_rrf:
            fused_results = reciprocal_rank_fusion(dense_results, sparse_results)
            results = fused_results[:top_k] if not self.reranker else fused_results
        else:
            # Naive hybrid (just combine and take unique, favor dense)
            results = dense_results.copy()
            seen_ids = {r["id"] for r in results}
            for r in sparse_results:
                if r["id"] not in seen_ids:
                    results.append(r)
                    seen_ids.add(r["id"])
                    
        if self.reranker:
            return self.reranker.rerank(query, results, top_k=top_k)
            
        return results[:top_k]
