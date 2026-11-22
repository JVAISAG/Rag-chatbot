from __future__ import annotations

from typing import List, TYPE_CHECKING
import numpy as np
import functools
import os
from dotenv import dotenv_values
from pathlib import Path
from src.errors import ModelUnavailableError


def configure_cpu_runtime():
    values = dotenv_values(Path(__file__).resolve().parents[2] / '.env')
    for key in ('TOKENIZERS_PARALLELISM', 'RAYON_NUM_THREADS', 'OMP_NUM_THREADS'):
        value = values.get(key)
        if value:
            os.environ.setdefault(key, value)
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')


configure_cpu_runtime()

os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

@functools.lru_cache(maxsize=1)
def get_embedding_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    """
    Load the sentence transformer model.
    Cached to avoid reloading.
    Forced to CPU to avoid CUDA initialization errors on limited hardware.
    """
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model_name, device="cpu")
    except Exception as exc:
        raise ModelUnavailableError("Embedding model unavailable. Run python scripts/prepare_models.py --embeddings first.") from exc

def generate_embeddings(texts: List[str], model: SentenceTransformer = None) -> np.ndarray:
    """
    Generate normalized embeddings for a list of texts in batch.
    """
    if not texts:
        return np.array([])

    if model is None:
        model = get_embedding_model()

    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
    return embeddings
