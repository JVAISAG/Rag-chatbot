from __future__ import annotations

import functools
import os
from pathlib import Path
from src.errors import ModelUnavailableError
from src.embeddings.models import configure_cpu_runtime
from typing import List, Dict, Any, TYPE_CHECKING
configure_cpu_runtime()

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

@functools.lru_cache(maxsize=1)
def get_cross_encoder(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> CrossEncoder:
    """Load the cross-encoder for reranking. Cached to avoid reloading."""
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name, device="cpu")
    except Exception as exc:
        raise ModelUnavailableError("Reranking model unavailable. Run python scripts/prepare_models.py --reranker first.") from exc

class CrossEncoderReranker:
    def __init__(self, model: CrossEncoder = None):
        self.model = model
        
    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """Rerank candidates using a cross-encoder."""
        if not candidates or top_k <= 0:
            return []
            
        if self.model is None:
            self.model = get_cross_encoder()
            
        # Prepare pairs of (query, document)
        pairs = [[query, item["text"]] for item in candidates]
        
        # Get relevance scores
        scores = self.model.predict(pairs)
        
        # Sort indices by score descending
        sorted_indices = sorted(range(len(scores)), key=lambda k: scores[k], reverse=True)
        
        output = []
        for rank, idx in enumerate(sorted_indices):
            if rank >= top_k:
                break
            item = candidates[idx].copy()
            item["score"] = float(scores[idx]) # Overwrite with cross-encoder score
            output.append(item)
            
        return output
