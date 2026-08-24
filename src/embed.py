import streamlit as st
from sentence_transformers import SentenceTransformer
from typing import List
import numpy as np

@st.cache_resource
def get_embedding_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    """
    Load the sentence transformer model. 
    Cached via Streamlit to avoid reloading on every UI interaction.
    Forced to CPU to avoid CUDA initialization errors on limited hardware.
    """
    # Initialize with device='cpu' to save VRAM for Ollama
    return SentenceTransformer(model_name, device="cpu")

def generate_embeddings(texts: List[str], model: SentenceTransformer = None) -> np.ndarray:
    """
    Generate normalized embeddings for a list of texts in batch.
    """
    if not texts:
        return np.array([])
        
    if model is None:
        model = get_embedding_model()
        
    # Generate embeddings
    # normalize_embeddings=True ensures cosine similarity behaves like dot product
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
    return embeddings

if __name__ == "__main__":
    # Test embedding generation
    sample_texts = ["What is the capital of France?", "Paris is the capital of France."]
    model = get_embedding_model()
    embeddings = generate_embeddings(sample_texts, model)
    print(f"Generated {len(embeddings)} embeddings of shape {embeddings.shape}")
    
    # Check normalization
    print(f"Norm of first embedding: {np.linalg.norm(embeddings[0]):.4f}")
