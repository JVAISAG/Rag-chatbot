import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Tuple
import numpy as np
from rank_bm25 import BM25Okapi

class VectorStore:
    def __init__(self, db_path: str = "./chroma_db", collection_name: str = "rag_documents"):
        """Initialize ChromaDB client and BM25 index."""
        # Ensure path exists
        os.makedirs(db_path, exist_ok=True)
        
        # Initialize ChromaDB persistent client
        self.client = chromadb.PersistentClient(path=db_path, settings=Settings(allow_reset=True))
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"} # Use cosine similarity for normalized vectors
        )
        
        # For hybrid search (Phase 2)
        self.bm25: BM25Okapi = None
        self.corpus_chunks: List[Dict[str, Any]] = []

    def build_bm25_index(self, chunks: List[Dict[str, Any]]):
        """Build the in-memory BM25 index from text chunks."""
        self.corpus_chunks = chunks
        
        # Simple tokenization by whitespace and lowercasing
        tokenized_corpus = [chunk["text"].lower().split() for chunk in chunks]
        
        if tokenized_corpus:
            self.bm25 = BM25Okapi(tokenized_corpus)
            print(f"BM25 index built with {len(self.corpus_chunks)} chunks.")
        else:
            self.bm25 = None

    def upsert_chunks(self, chunks: List[Dict[str, Any]], embeddings: np.ndarray):
        """Upsert document chunks and their dense embeddings into ChromaDB."""
        if not chunks:
            return
            
        ids = []
        documents = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            # Create a unique ID for each chunk based on source and index
            source = chunk["metadata"].get("source", "unknown")
            chunk_idx = chunk["metadata"].get("chunk_index", i)
            doc_id = f"{source}_{chunk_idx}"
            
            ids.append(doc_id)
            documents.append(chunk["text"])
            
            # Ensure metadata values are basic types (str, int, float, bool)
            meta = {}
            for k, v in chunk["metadata"].items():
                if isinstance(v, (str, int, float, bool)):
                    meta[k] = v
                else:
                    meta[k] = str(v)
            metadatas.append(meta)
            
        # Batch upsert to Chroma
        batch_size = 5000
        for i in range(0, len(ids), batch_size):
            self.collection.upsert(
                ids=ids[i:i+batch_size],
                embeddings=embeddings[i:i+batch_size].tolist(),
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size]
            )
            
        # Rebuild BM25 index for sparse search
        self.build_bm25_index(chunks)

    def dense_search(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        """Perform dense search using ChromaDB."""
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )
        
        output = []
        if results and results['ids'] and results['ids'][0]:
            for i in range(len(results['ids'][0])):
                output.append({
                    "id": results['ids'][0][i],
                    "text": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "distance": results['distances'][0][i], # Lower is better in Chroma
                    "score": 1.0 - results['distances'][0][i] # Approximate similarity score
                })
        return output

    def sparse_search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
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
                    "score": scores[idx]
                })
        return output

if __name__ == "__main__":
    # Minimal test
    store = VectorStore(db_path="./test_chroma")
    print(f"Collection count: {store.collection.count()}")
