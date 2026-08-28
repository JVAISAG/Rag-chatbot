from typing import List, Dict, Any
from src.retrieval.base import Retriever
from src.storage.vector_store import VectorStore
from src.embeddings.models import generate_embeddings, SentenceTransformer

class DenseRetriever(Retriever):
    def __init__(self, store: VectorStore, embedding_model: SentenceTransformer):
        self.store = store
        self.embedding_model = embedding_model
        
    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        query_embedding = generate_embeddings([query], self.embedding_model)[0]
        return self.store.dense_search(query_embedding, top_k=top_k)
