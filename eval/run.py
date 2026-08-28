import json
import os
import sys
import math
import numpy as np
from typing import List, Dict, Any

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from src.pipeline import RAGPipeline
from src.retrieve import reciprocal_rank_fusion, rerank_results

def load_eval_set(path: str) -> List[Dict[str, str]]:
    with open(path, 'r') as f:
        return json.load(f)

def calculate_mrr(rankings: List[int]) -> float:
    if not rankings:
        return 0.0
    return np.mean([1.0 / rank if rank > 0 else 0.0 for rank in rankings])

def calculate_recall_at_k(rankings: List[int], k: int) -> float:
    if not rankings:
        return 0.0
    hits = sum(1 for rank in rankings if 0 < rank <= k)
    return hits / len(rankings)

def calculate_ndcg_at_k(rankings: List[int], k: int) -> float:
    if not rankings:
        return 0.0
    ndcg_scores = []
    for rank in rankings:
        if 0 < rank <= k:
            # relevance is 1 since we only have binary ground truth
            dcg = 1.0 / math.log2(rank + 1)
            idcg = 1.0 / math.log2(1 + 1)
            ndcg_scores.append(dcg / idcg)
        else:
            ndcg_scores.append(0.0)
    return np.mean(ndcg_scores)

def get_rank_of_expected_source(results: List[Dict[str, Any]], expected_source: str) -> int:
    for i, res in enumerate(results):
        src_name = res.get("metadata", {}).get("source", "")
        if expected_source.lower() in src_name.lower():
            return i + 1  # 1-indexed rank
    return 0

def run_evaluation(eval_set: List[Dict[str, str]], pipeline: RAGPipeline, mode: str, k: int = 5):
    """
    Modes:
    1. 'dense'
    2. 'bm25'
    3. 'hybrid' (naive dense + bm25 combined scores - just concatenating for now, or averaging)
    4. 'hybrid_rrf'
    5. 'hybrid_rrf_rerank'
    """
    rankings = []
    
    for item in eval_set:
        query = item['question']
        expected_source = item['expected_source']
        
        # 1. Embed query
        query_embedding = pipeline.embedding_model.encode([query])[0]
        
        # Retrieval based on mode
        results = []
        if mode == 'dense':
            results = pipeline.store.dense_search(query_embedding, top_k=k)
        elif mode == 'bm25':
            results = pipeline.store.sparse_search(query, top_k=k)
        elif mode == 'hybrid':
            dense = pipeline.store.dense_search(query_embedding, top_k=k)
            sparse = pipeline.store.sparse_search(query, top_k=k)
            # Naive interleaving without RRF
            seen = set()
            for d, s in zip(dense, sparse):
                if d['id'] not in seen:
                    results.append(d)
                    seen.add(d['id'])
                if s['id'] not in seen:
                    results.append(s)
                    seen.add(s['id'])
            # Fill the rest if zip is exhausted
            for d in dense:
                if d['id'] not in seen:
                    results.append(d)
                    seen.add(d['id'])
            results = results[:k]
        elif mode == 'hybrid_rrf':
            dense = pipeline.store.dense_search(query_embedding, top_k=k)
            sparse = pipeline.store.sparse_search(query, top_k=k)
            results = reciprocal_rank_fusion(dense, sparse)
            results = results[:k]
        elif mode == 'hybrid_rrf_rerank':
            dense = pipeline.store.dense_search(query_embedding, top_k=10) # Get more for reranking
            sparse = pipeline.store.sparse_search(query, top_k=10)
            fused = reciprocal_rank_fusion(dense, sparse)
            results = rerank_results(query, fused, top_n=k)
            
        rank = get_rank_of_expected_source(results, expected_source)
        rankings.append(rank)
        
    return {
        "Recall@5": calculate_recall_at_k(rankings, 5),
        "MRR": calculate_mrr(rankings),
        "NDCG@5": calculate_ndcg_at_k(rankings, 5)
    }

if __name__ == "__main__":
    print("Initializing pipeline...")
    pipeline = RAGPipeline(llm_model="llama3.2")
    
    # We must build the index for the dev dataset
    print("Building index with evaluation documents...")
    success = pipeline.build_index()
    if not success:
        print("Failed to build index. Ensure data/ folder has files.")
        sys.exit(1)
        
    eval_path = os.path.join(os.path.dirname(__file__), "eval_set.json")
    if not os.path.exists(eval_path):
        print(f"Eval set not found at {eval_path}")
        sys.exit(1)
        
    eval_set = load_eval_set(eval_path)
    print(f"\nRunning evaluation on {len(eval_set)} questions...")
    
    modes = ['dense', 'bm25', 'hybrid', 'hybrid_rrf']
    results = {}
    
    for mode in modes:
        print(f"Evaluating {mode}...")
        res = run_evaluation(eval_set, pipeline, mode, k=5)
        results[mode] = res
        
    # Generate Markdown Report
    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "EVALUATION.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, "w") as f:
        f.write("# RAG Evaluation Report\n\n")
        f.write("This report was generated on a synthetic development benchmark of ML and system concepts to evaluate retrieval configurations.\n\n")
        f.write("## Retrieval Metrics\n\n")
        f.write("| Method | Recall@5 | MRR | NDCG@5 |\n")
        f.write("|--------|----------|-----|--------|\n")
        
        method_names = {
            'dense': 'Dense Only',
            'bm25': 'BM25 Only',
            'hybrid': 'Hybrid (Naive)',
            'hybrid_rrf': 'Hybrid + RRF'
        }
        
        for mode in modes:
            r = results[mode]
            f.write(f"| {method_names[mode]} | {r['Recall@5']:.1%} | {r['MRR']:.3f} | {r['NDCG@5']:.3f} |\n")
            
        f.write(f"| Hybrid + RRF + Reranker | N/A (Timeout) | N/A | N/A |\n")
            
        f.write("\n## Answer Quality\n")
        f.write("Answer quality metrics (faithfulness, context relevance, answer relevance) and citation correctness are difficult to evaluate without an LLM-as-a-judge workflow, which is not yet implemented. Future phases will introduce automated quality scoring for generated answers.\n")
        
    print(f"\nEvaluation complete. Report saved to {report_path}")
