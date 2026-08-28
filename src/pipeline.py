from typing import List, Dict, Any, Tuple
import os

from src.ingestion.document_loader import load_documents
from src.chunking.text_splitter import process_documents
from src.embeddings.models import generate_embeddings, get_embedding_model
from src.storage.vector_store import VectorStore
from src.retrieval.dense import DenseRetriever
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.reranker import CrossEncoderReranker
from src.retrieval.hybrid import HybridRetriever
from src.generation.llm import LLMGenerator

from src.agents.router import QueryRouter

class RAGPipeline:
    def __init__(self, data_dir: str = "./data", db_path: str = "./chroma_db", llm_model: str = "llama3.2"):
        self.data_dir = data_dir
        self.store = VectorStore(db_path=db_path)
        self.embedding_model = get_embedding_model()
        self.llm_generator = LLMGenerator(model_name=llm_model)
        self.router = QueryRouter(model_name=llm_model)
        
        # Initialize retrievers
        self.dense_retriever = DenseRetriever(self.store, self.embedding_model)
        self.sparse_retriever = BM25Retriever()
        
        # We optionally load reranker if hybrid is requested, but for pipeline initialization we can leave it none 
        # and instantiate lazily or on demand if the user wants to save memory.
        self.reranker = CrossEncoderReranker() 
        
        # The hybrid retriever orchestrates dense + sparse + reranker
        self.hybrid_retriever = HybridRetriever(
            dense_retriever=self.dense_retriever,
            sparse_retriever=self.sparse_retriever,
            reranker=self.reranker
        )
        
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
        
        # Fit BM25 in memory (In production, this would be serialized/persisted)
        self.sparse_retriever.fit(chunks)
        
        print("Index built successfully.")
        return True
        
    def query(self, 
              user_query: str, 
              history: List[Dict[str, str]] = None,
              use_hybrid: bool = False,
              use_reranking: bool = False) -> Tuple[str, List[Dict[str, Any]]]:
        """End-to-end retrieval and generation with agentic routing."""
        
        # 1. Condense query if history exists
        actual_query = user_query
        if history:
            actual_query = self.llm_generator.condense_query(user_query, history)
            print(f"Original Query: {user_query}")
            print(f"Condensed Query: {actual_query}")
            
        # 2. Route the query
        intent = self.router.route_query(actual_query)
        print(f"Query classified as: {intent}")
        
        if intent == "SMALL_TALK":
            answer = self.llm_generator.generate_small_talk_answer(actual_query)
            return answer, []
            
        # Determine retrieval K based on intent
        top_k = 15 if intent == "SUMMARIZATION" else 5
            
        # 3. Retrieve chunks
        if use_hybrid:
            # Temporarily disable reranker if use_reranking is False
            original_reranker = self.hybrid_retriever.reranker
            if not use_reranking:
                self.hybrid_retriever.reranker = None
                
            chunks = self.hybrid_retriever.retrieve(query=actual_query, top_k=top_k, use_rrf=True)
            
            # Restore reranker
            self.hybrid_retriever.reranker = original_reranker
        else:
            chunks = self.dense_retriever.retrieve(query=actual_query, top_k=top_k)
            
        # 4. Generate Answer
        answer, sources = self.llm_generator.generate_answer(actual_query, chunks)
        
        return answer, sources
