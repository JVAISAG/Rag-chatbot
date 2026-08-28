from typing import List, Dict, Any
import numpy as np
from rank_bm25 import BM25Okapi
from src.retrieval.base import Retriever

class BM25Retriever(Retriever):
    def __init__(self):
        self.bm25: BM25Okapi = None
        self.corpus_chunks: List[Dict[str, Any]] = []

    def fit(self, chunks: List[Dict[str, Any]]):
        """Build the in-memory BM25 index from text chunks."""
        self.corpus_chunks = chunks
        tokenized_corpus = [chunk["text"].lower().split() for chunk in chunks]
        
        if tokenized_corpus:
            self.bm25 = BM25Okapi(tokenized_corpus)
        else:
            self.bm25 = None
            
    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Perform sparse (keyword) search using BM25."""
        if self.bm25 is None or not self.corpus_chunks:
            return []
            
        tokenized_query = query.lower().split()
        scores = self.bm25.get_scores(tokenized_query)
        
        # Get top k indices
        top_indices = np.argsort(scores)[::-1][:top_k]
        
        output = []
        for idx in top_indices:
            if scores[idx] > 0: # Only return chunks that have some match
                chunk = self.corpus_chunks[idx]
                output.append({
                    "id": f"{chunk['metadata'].get('source', 'unknown')}_{chunk['metadata'].get('chunk_index', idx)}",
                    "text": chunk["text"],
                    "metadata": chunk["metadata"],
                    "score": float(scores[idx])
                })
        return output
