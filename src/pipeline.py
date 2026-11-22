from pathlib import Path
from contextlib import ExitStack
import logging
import re
from threading import RLock
from typing import Any, Dict, List, Tuple
import uuid

import numpy as np

from src.ingestion.document_loader import load_document, load_documents
from src.chunking.text_splitter import process_documents
from src.embeddings.models import generate_embeddings, get_embedding_model
from src.errors import DocumentError
from src.storage.vector_store import VectorStore
from src.retrieval.dense import DenseRetriever
from src.retrieval.bm25 import BM25Retriever
from src.retrieval.reranker import CrossEncoderReranker
from src.retrieval.hybrid import HybridRetriever
from src.generation.llm import LLMGenerator
from src.generation.client import DEFAULT_MODEL
from src.agents.router import QueryRouter
from src.agents.web_search import WebSearchTool


class RAGPipeline:
    def __init__(self, data_dir="./data", db_path="./chroma_db", llm_model=DEFAULT_MODEL, *,
                 store=None, embedding_model=None, llm_generator=None, router=None):
        self.data_dir = str(Path(data_dir).resolve())
        self._lock = RLock()
        self.store = store if store is not None else VectorStore(db_path=db_path)
        self._embedding_model = embedding_model
        self.llm_generator = llm_generator or LLMGenerator(model_name=llm_model)
        self.router = router or QueryRouter(model_name=llm_model)
        self.web_search = WebSearchTool(max_results=5)
        self.dense_retriever = DenseRetriever(self.store, embedding_model)
        self.sparse_retriever = BM25Retriever()
        # One authoritative corpus: no separate stale/global pickle index.
        current = self.store.get_all_chunks()
        self._recover_staged_files(current)
        self.sparse_retriever.fit(current)
        self.reranker = CrossEncoderReranker()
        self.hybrid_retriever = HybridRetriever(self.dense_retriever, self.sparse_retriever, self.reranker)

    def close(self):
        with ExitStack() as cleanup:
            cleanup.callback(self.router.client.close)
            cleanup.callback(self.llm_generator.client.close)
            cleanup.callback(self.store.close)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def embedding_model(self):
        if self._embedding_model is None:
            self._embedding_model = get_embedding_model()
            self.dense_retriever.embedding_model = self._embedding_model
        return self._embedding_model

    def _embeddings(self, chunks):
        if not chunks:
            return np.empty((0, 0))
        return generate_embeddings([chunk["text"] for chunk in chunks], self.embedding_model)

    def _chunk_documents(self, documents):
        if not documents:
            return []
        model = self.embedding_model
        limit = min(500, getattr(model, "max_seq_length", 500))
        tokenizer = getattr(model, "tokenizer", None)
        counter = (lambda text: len(tokenizer.encode(text, add_special_tokens=True))) if tokenizer is not None else None
        return process_documents(documents, chunk_size=limit, overlap=min(50, limit // 5), token_counter=counter)

    def _safe_path(self, file_path):
        path = Path(file_path).resolve()
        if not path.is_relative_to(Path(self.data_dir)) or path == Path(self.data_dir):
            raise DocumentError("Document paths must stay inside the data directory.")
        return path

    def _source_overrides(self, chunks):
        overrides = {}
        for chunk in chunks:
            meta = chunk["metadata"]
            if meta.get("filepath"):
                path = str(Path(meta["filepath"]).resolve())
                source = meta["source"]
                # Older uploads indexed the same path under a UUID and its real name.
                if path not in overrides or source != Path(path).name:
                    overrides[path] = source
        return overrides

    def _recover_staged_files(self, chunks):
        referenced = {str(Path(chunk["metadata"]["filepath"]).resolve())
                      for chunk in chunks if chunk["metadata"].get("filepath")}
        for temporary in Path(self.data_dir).rglob("*.pending-delete"):
            match = re.fullmatch(r"\.(.+)\.([0-9a-f]{32})\.pending-delete", temporary.name)
            if not match:
                continue
            original = self._safe_path(temporary.with_name(match.group(1)))
            if str(original) in referenced:
                if not original.exists():
                    temporary.rename(original)
            else:
                temporary.unlink()

    def build_index(self):
        with self._lock:
            previous = self.store.get_all_chunks()
            docs = load_documents(self.data_dir, self._source_overrides(previous))
            chunks = self._chunk_documents(docs)
            embeddings = self._embeddings(chunks)
            # Prepare the sparse index before any writes, including the empty case.
            sparse = BM25Retriever()
            sparse.fit(chunks)
            self.store.replace_chunks(chunks, embeddings)
            self.sparse_retriever = sparse
            self.hybrid_retriever.sparse = sparse
            return True

    def ingest_file(self, file_path: str, filename: str) -> bool:
        with self._lock:
            path = self._safe_path(file_path)
            docs = load_document(str(path), filename)
            current = self.store.get_all_chunks()
            existing = [chunk for chunk in current if chunk["metadata"].get("source") == filename]
            digest = docs[0]["metadata"]["file_hash"]
            if existing and all(chunk["metadata"].get("file_hash") == digest for chunk in existing):
                retained = {str(Path(chunk["metadata"]["filepath"]).resolve()) for chunk in existing}
                if str(path) not in retained:
                    path.unlink()
                return True
            chunks = self._chunk_documents(docs)
            embeddings = self._embeddings(chunks)
            sparse = BM25Retriever()
            sparse.fit([chunk for chunk in current if chunk["metadata"].get("source") != filename] + chunks)
            old_paths = {self._safe_path(chunk["metadata"]["filepath"]) for chunk in existing if chunk["metadata"].get("filepath")}
            staged = self._stage_files(old_paths - {path})
            try:
                self.store.replace_chunks(chunks, embeddings, source=filename)
            except Exception:
                self._restore_files(staged)
                raise
            self.sparse_retriever = sparse
            self.hybrid_retriever.sparse = sparse
            self._finish_files(staged)
            return True

    def _stage_files(self, paths):
        staged = []
        try:
            for path in paths:
                if path.exists():
                    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending-delete")
                    path.rename(temporary)
                    staged.append((path, temporary))
            return staged
        except Exception:
            self._restore_files(staged)
            raise

    @staticmethod
    def _restore_files(staged):
        for original, temporary in staged:
            temporary.rename(original)

    @staticmethod
    def _finish_files(staged):
        for _, temporary in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("A staged document could not be removed; it will not be indexed.")

    def remove_file(self, filename: str) -> bool:
        with self._lock:
            current = self.store.get_all_chunks()
            existing = [chunk for chunk in current if chunk["metadata"].get("source") == filename]
            if not existing:
                return False
            sparse = BM25Retriever()
            sparse.fit([chunk for chunk in current if chunk["metadata"].get("source") != filename])
            paths = {self._safe_path(chunk["metadata"]["filepath"]) for chunk in existing if chunk["metadata"].get("filepath")}
            staged = self._stage_files(paths)
            try:
                self.store.delete_by_source(filename)
            except Exception:
                self._restore_files(staged)
                raise
            self.sparse_retriever = sparse
            self.hybrid_retriever.sparse = sparse
            self._finish_files(staged)
            return True

    def list_files(self):
        with self._lock:
            counts = {}
            for chunk in self.store.get_all_chunks():
                source = chunk["metadata"].get("source", "Unknown")
                counts[source] = counts.get(source, 0) + 1
            return [{"name": name, "chunks": count} for name, count in sorted(counts.items())]

    def query(self, user_query: str, history: List[Dict[str, str]] = None,
              use_hybrid: bool = False, use_reranking: bool = False) -> Tuple[str, List[Dict[str, Any]]]:
        actual_query = self.llm_generator.condense_query(user_query, history) if history else user_query
        intent = self.router.route_query(actual_query)
        if intent == "SMALL_TALK":
            return self.llm_generator.generate_small_talk_answer(actual_query), []
        if intent == "WEB_SEARCH":
            return self.llm_generator.generate_answer(actual_query, self.web_search.search(actual_query))
        top_k = 15 if intent == "SUMMARIZATION" else 5
        with self._lock:
            if use_hybrid:
                chunks = self.hybrid_retriever.retrieve(actual_query, top_k, use_reranking=use_reranking)
            else:
                chunks = self.dense_retriever.retrieve(actual_query, top_k=top_k * 2 if use_reranking else top_k)
                if use_reranking:
                    chunks = self.reranker.rerank(actual_query, chunks, top_k=top_k)
        return self.llm_generator.generate_answer(actual_query, chunks)
