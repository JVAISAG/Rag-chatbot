import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
from collections import Counter
from typing import Any, Dict, List

import numpy as np
from rank_bm25 import BM25Okapi

from src.retrieval.base import Retriever

logger = logging.getLogger(__name__)


def tokenize(text: str) -> List[str]:
    return re.findall(r"\w+(?:[-.]\w+)*", text.casefold())


class BM25Retriever(Retriever):
    def __init__(self):
        self.bm25 = None
        self.corpus_chunks = []

    def fit(self, chunks: List[Dict[str, Any]]):
        corpus = [(chunk, tokenize(chunk["text"])) for chunk in chunks]
        corpus = [(chunk, tokens) for chunk, tokens in corpus if tokens]
        self.corpus_chunks = [chunk for chunk, _ in corpus]
        if not corpus:
            self.bm25 = None
            return
        tokens = [words for _, words in corpus]
        self.bm25 = BM25Okapi(tokens)
        # Positive IDF also handles one-document and two-document collections.
        frequencies = Counter(term for document in self.bm25.doc_freqs for term in document)
        for term, count in frequencies.items():
            self.bm25.idf[term] = math.log(1 + (len(tokens) - count + 0.5) / (count + 0.5))

    def save(self, file_path: str = "./data/bm25_index.json"):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.corpus_chunks, stream, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self, file_path: str = "./data/bm25_index.json") -> bool:
        # Never unpickle index files. The pipeline reconstructs BM25 from Chroma.
        if Path(file_path).suffix.lower() != ".json":
            return False
        try:
            chunks = json.loads(Path(file_path).read_text(encoding="utf-8"))
            self.fit(chunks)
            return True
        except (OSError, ValueError, TypeError, KeyError):
            logger.warning("Could not load sparse index; rebuild it from the vector store.")
            return False

    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        if self.bm25 is None or top_k <= 0:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self.bm25.get_scores(tokens)
        indices = np.argsort(-scores, kind="stable")[:top_k]
        output = []
        for idx in indices:
            if scores[idx] > 0:
                chunk = self.corpus_chunks[idx]
                output.append({
                    **chunk,
                    "id": chunk.get("id", f"{chunk['metadata'].get('source', 'unknown')}_{chunk['metadata'].get('chunk_index', idx)}"),
                    "score": float(scores[idx]),
                })
        return output
