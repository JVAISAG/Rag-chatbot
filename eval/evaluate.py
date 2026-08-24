import json
import os
import sys
from typing import List, Dict, Any

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from src.pipeline import RAGPipeline

def load_eval_set(path: str) -> List[Dict[str, str]]:
    with open(path, 'r') as f:
        return json.load(f)

def run_evaluation(eval_set: List[Dict[str, str]], pipeline: RAGPipeline, use_hybrid: bool, use_reranking: bool):
    """Run evaluation and return precision@3"""
    correct_retrievals = 0
    total = len(eval_set)
    
    for item in eval_set:
        query = item['question']
        expected_source = item['expected_source']
        
        # We only care about retrieval here, so we could bypass generation
        # But for full e2e we'll run the pipeline and check sources
        _, sources = pipeline.query(
            user_query=query, 
            use_hybrid=use_hybrid, 
            use_reranking=use_reranking
        )
        
        # Check if expected source is in retrieved sources
        found = False
        for source in sources:
            src_name = source.get("metadata", {}).get("source", "")
            if expected_source.lower() in src_name.lower():
                found = True
                break
                
        if found:
            correct_retrievals += 1
            
    precision = correct_retrievals / total if total > 0 else 0
    return precision

if __name__ == "__main__":
    # Ensure index exists or build it
    pipeline = RAGPipeline(llm_model="llama3.2")
    
    # Normally we'd build the index first before evaluation
    # pipeline.build_index()
    
    eval_path = os.path.join(os.path.dirname(__file__), "eval_set.json")
    if not os.path.exists(eval_path):
        print(f"Eval set not found at {eval_path}")
        sys.exit(1)
        
    eval_set = load_eval_set(eval_path)
    print(f"Running evaluation on {len(eval_set)} questions...\n")
    
    # Note: Requires chunks to actually exist in ChromaDB to test properly
    # If the DB is empty, this will yield 0.0
    
    # 1. Baseline Dense Only
    print("Evaluating Baseline (Dense Only)...")
    baseline_p = run_evaluation(eval_set, pipeline, use_hybrid=False, use_reranking=False)
    
    # 2. Hybrid Search
    print("Evaluating Hybrid Search (Dense + BM25)...")
    hybrid_p = run_evaluation(eval_set, pipeline, use_hybrid=True, use_reranking=False)
    
    # 3. Hybrid + Re-ranking
    print("Evaluating Hybrid + Re-ranking (Cross-Encoder)...")
    rerank_p = run_evaluation(eval_set, pipeline, use_hybrid=True, use_reranking=True)
    
    print("\n=== Evaluation Results (Precision@3) ===")
    print(f"Baseline (Dense Only): {baseline_p:.2f}")
    print(f"Hybrid (Dense+Sparse): {hybrid_p:.2f}")
    print(f"Hybrid + Re-ranking  : {rerank_p:.2f}")
    print("========================================")
