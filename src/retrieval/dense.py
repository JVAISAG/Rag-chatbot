from __future__ import annotations

from typing import List, Dict, Any, TYPE_CHECKING
from src.retrieval.base import Retriever
from src.storage.vector_store import VectorStore
from src.embeddings.models import generate_embeddings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

class DenseRetriever(Retriever):
    def __init__(self, store: VectorStore, embedding_model: SentenceTransformer):
        self.store = store
        self.embedding_model = embedding_model
        
    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if top_k <= 0 or not query.strip():
            return []
        query_embedding = generate_embeddings([query], self.embedding_model)[0]
        return self.store.dense_search(query_embedding, top_k=top_k)
