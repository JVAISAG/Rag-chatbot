from typing import List, Dict, Any, Tuple
import os
from src.ingest import load_documents
from src.chunk import process_documents
from src.embed import generate_embeddings, get_embedding_model
from src.store import VectorStore
from src.retrieve import retrieve, condense_query
from src.generate import generate_answer

class RAGPipeline:
    def __init__(self, data_dir: str = "./data", db_path: str = "./chroma_db", llm_model: str = "llama3.2"):
        self.data_dir = data_dir
        self.store = VectorStore(db_path=db_path)
        self.embedding_model = get_embedding_model()
        self.llm_model = llm_model
        
    def build_index(self):
        """End-to-end ingestion, chunking, embedding, and indexing."""
        print("Loading documents...")
        docs = load_documents(self.data_dir)
        if not docs:
            print("No documents found.")
            return False
            
        print("Chunking documents...")
        chunks = process_documents(docs)
        
        print("Generating embeddings...")
        texts = [c["text"] for c in chunks]
        embeddings = generate_embeddings(texts, self.embedding_model)
        
        print("Upserting to vector store...")
        self.store.upsert_chunks(chunks, embeddings)
        print("Index built successfully.")
        return True
        
    def query(self, 
              user_query: str, 
              history: List[Dict[str, str]] = None,
              use_hybrid: bool = False,
              use_reranking: bool = False) -> Tuple[str, List[Dict[str, Any]]]:
        """End-to-end retrieval and generation."""
        
        # 1. Condense query if history exists
        actual_query = user_query
        if history:
            actual_query = condense_query(user_query, history, model=self.llm_model)
            print(f"Original Query: {user_query}")
            print(f"Condensed Query: {actual_query}")
            
        # 2. Retrieve chunks
        chunks = retrieve(
            query=actual_query,
            store=self.store,
            embedding_model=self.embedding_model,
            use_hybrid=use_hybrid,
            use_reranking=use_reranking
        )
        
        # 3. Generate Answer
        answer, sources = generate_answer(actual_query, chunks, model=self.llm_model)
        
        return answer, sources
