import streamlit as st
from sentence_transformers import CrossEncoder, SentenceTransformer
from typing import List, Dict, Any
import numpy as np
import ollama
from src.store import VectorStore
from src.embed import generate_embeddings, get_embedding_model

@st.cache_resource
def get_cross_encoder(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> CrossEncoder:
    """Load the cross-encoder model for re-ranking."""
    return CrossEncoder(model_name, device="cpu")

def condense_query(query: str, history: List[Dict[str, str]], model: str = "llama3.2") -> str:
    """
    Rewrite a follow-up question to be standalone using conversation history.
    """
    if not history:
        return query
        
    prompt = (
        "Given the following conversation history and a follow-up question, "
        "rewrite the follow-up question to be a standalone question that can be "
        "understood without the history. Do not answer the question, just rewrite it.\n\n"
        "History:\n"
    )
    
    # Take last 2 turns
    recent_history = history[-2:] if len(history) >= 2 else history
    for turn in recent_history:
        prompt += f"{turn['role'].capitalize()}: {turn['content']}\n"
        
    prompt += f"\nFollow-up question: {query}\nStandalone question:"
    
    try:
        response = ollama.generate(model=model, prompt=prompt)
        condensed = response['response'].strip()
        # Basic validation: if the rewrite is suspiciously long or contains generic AI phrases, fallback
        if len(condensed) > len(query) * 3 or "here is the rewritten" in condensed.lower():
            return query
        return condensed
    except Exception as e:
        print(f"Error condensing query: {e}")
        return query

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
        item = chunk_map[doc_id]
        item["rrf_score"] = fused_scores[doc_id]
        output.append(item)
        
    return output

def rerank_results(query: str, chunks: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    """Re-rank candidate chunks using a Cross-Encoder."""
    if not chunks:
        return []
        
    cross_encoder = get_cross_encoder()
    
    # Create pairs of (query, chunk_text)
    pairs = [[query, chunk["text"]] for chunk in chunks]
    
    # Score pairs
    scores = cross_encoder.predict(pairs)
    
    # Sort chunks by score
    for i, chunk in enumerate(chunks):
        chunk["rerank_score"] = float(scores[i])
        
    # Sort descending
    reranked = sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:top_n]

def retrieve(query: str, 
             store: VectorStore, 
             embedding_model: SentenceTransformer,
             use_hybrid: bool = False, 
             use_reranking: bool = False,
             top_k: int = 10,
             final_k: int = 3) -> List[Dict[str, Any]]:
    """Main retrieval pipeline orchestrator."""
    
    # 1. Embed query
    query_embedding = generate_embeddings([query], embedding_model)[0]
    
    # 2. Dense search
    results = store.dense_search(query_embedding, top_k=top_k)
    
    # 3. Optional: Sparse search & Hybrid fusion
    if use_hybrid:
        sparse_results = store.sparse_search(query, top_k=top_k)
        results = reciprocal_rank_fusion(results, sparse_results)
    
    # 4. Optional: Re-ranking
    if use_reranking:
        # Cross encoder is computationally expensive, so only rerank the top_k
        results = rerank_results(query, results[:top_k], top_n=final_k)
    else:
        results = results[:final_k]
        
    return results
