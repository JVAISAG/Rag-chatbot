from typing import Any, Dict, List

import numpy as np


class VectorStore:
    def __init__(self, db_path: str = "./chroma_db", collection_name: str = "rag_documents"):
        # Importing the API or a test must not initialize Chroma or download models.
        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(path=db_path, settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    def close(self):
        self.client.close()

    def _payload(self, chunks, embeddings):
        embeddings = np.asarray(embeddings)
        if len(chunks) != len(embeddings):
            raise ValueError("Each chunk must have exactly one embedding.")
        if chunks and (embeddings.ndim != 2 or not np.isfinite(embeddings).all()):
            raise ValueError("Embeddings must be a finite two-dimensional array.")
        ids, documents, metadatas = [], [], []
        for i, chunk in enumerate(chunks):
            metadata = chunk["metadata"]
            ids.append(chunk.get("id", f"{metadata.get('source', 'unknown')}_{metadata.get('chunk_index', i)}"))
            documents.append(chunk["text"])
            metadatas.append({
                key: value if isinstance(value, (str, int, float, bool)) else str(value)
                for key, value in metadata.items() if value is not None
            })
        if len(set(ids)) != len(ids):
            raise ValueError("Chunk IDs must be unique.")
        return {"ids": ids, "documents": documents, "metadatas": metadatas, "embeddings": embeddings.tolist()}

    def _upsert_payload(self, payload):
        for start in range(0, len(payload["ids"]), 1000):
            self.collection.upsert(**{key: values[start:start + 1000] for key, values in payload.items()})

    def upsert_chunks(self, chunks: List[Dict[str, Any]], embeddings: np.ndarray):
        if chunks:
            self._upsert_payload(self._payload(chunks, embeddings))

    def get_all_chunks(self) -> List[Dict[str, Any]]:
        result = self.collection.get(include=["documents", "metadatas"])
        return [
            {"id": identifier, "text": result["documents"][i], "metadata": result["metadatas"][i]}
            for i, identifier in enumerate(result["ids"])
        ]

    def replace_chunks(self, chunks, embeddings, source=None):
        """Replace a source (or the full index), removing stale chunks.

        Restore the previous records if a write fails. The pipeline serializes
        readers and writers; Chroma does not offer a cross-call transaction.
        """
        payload = self._payload(chunks, embeddings)
        filters = {"where": {"source": source}} if source is not None else {}
        previous = self.collection.get(include=["documents", "metadatas", "embeddings"], **filters)
        old_ids, new_ids = set(previous["ids"]), set(payload["ids"])
        try:
            self._upsert_payload(payload)
            stale = list(old_ids - new_ids)
            for start in range(0, len(stale), 1000):
                self.collection.delete(ids=stale[start:start + 1000])
        except Exception:
            if old_ids:
                self._upsert_payload({
                    "ids": previous["ids"], "documents": previous["documents"],
                    "metadatas": previous["metadatas"], "embeddings": np.asarray(previous["embeddings"]).tolist(),
                })
            added = list(new_ids - old_ids)
            if added:
                self.collection.delete(ids=added)
            raise

    def delete_by_source(self, source: str):
        self.replace_chunks([], np.empty((0, 0)), source=source)

    def dense_search(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Dict[str, Any]]:
        count = self.collection.count()
        if count == 0 or top_k <= 0:
            return []
        results = self.collection.query(
            query_embeddings=[np.asarray(query_embedding).tolist()], n_results=min(top_k, count),
            include=["documents", "metadatas", "distances"],
        )
        return [
            {
                "id": identifier, "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i], "distance": results["distances"][0][i],
                "score": 1.0 - results["distances"][0][i],
            }
            for i, identifier in enumerate(results["ids"][0])
        ]
