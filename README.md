# Personal RAG Chatbot (Fully Local)

A robust Retrieval-Augmented Generation (RAG) chatbot designed to answer questions over personal documents (PDFs, DOCX, Markdown) using a **100% local, free architecture**.

## Features & Architecture

This project implements an advanced retrieval pipeline built from scratch to demonstrate production-grade RAG concepts:

1. **Token-Aware Chunking:** Uses `tiktoken` to split text by tokens (not characters), preventing context window overflows.
2. **Hybrid Search (Dense + Sparse):**
   - **Dense:** `sentence-transformers` (`all-MiniLM-L6-v2`) + ChromaDB (HNSW).
   - **Sparse:** `rank_bm25` in-memory index for exact keyword matching (acronyms, dates).
3. **Reciprocal Rank Fusion (RRF):** Fuses dense and sparse rankings without score normalization issues.
4. **Cross-Encoder Re-ranking:** Uses `ms-marco-MiniLM-L-6-v2` to jointly score query and candidate chunks, significantly improving top-K precision.
5. **Local LLM Generation:** Uses Ollama (`llama3.2` 3B model) for free, local answer generation with inline citations.
6. **Query Condensing:** Rewrites follow-up questions into standalone queries based on chat history.

## Setup & Execution

### Prerequisites
1. **Ollama:** Install [Ollama](https://ollama.com/) and pull the model:
   ```bash
   ollama pull llama3.2
   ```
2. **Python Environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

### Running the App
1. Place your documents (`.pdf`, `.docx`, `.md`, `.txt`) in the `data/` folder.
2. Launch the Streamlit app:
   ```bash
   streamlit run app.py
   ```
3. Click "Build/Rebuild Index" in the sidebar to ingest and embed your documents.
4. Use the sidebar toggles to experiment with Hybrid Search and Cross-Encoder Re-ranking.

## Design Decisions

### 1. Bi-Encoder vs. Cross-Encoder
Initial retrieval uses a fast Bi-Encoder (`all-MiniLM-L6-v2`) to narrow down thousands of chunks to the Top 10 in milliseconds using ChromaDB's HNSW graph. We then apply an expensive, highly accurate Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) only on those Top 10 chunks to re-rank and pick the best 3. This balances O(1) ANN search speed with O(N) Cross-Encoder precision.

### 2. Chunking Strategy
Chunks are roughly ~500 tokens with a ~50-token overlap, sized via `tiktoken`. We split recursively (Paragraphs -> Sentences) to ensure chunks contain coherent ideas and prevent "lost in the middle" effects during LLM generation.

### 3. Fully Local Stack
No paid APIs. We chose a 3B model (`llama3.2`) to comfortably fit within 8GB of system RAM alongside Python, Streamlit, and the two embedding models, without causing out-of-memory (OOM) errors.

## Evaluation

We evaluate the retrieval pipeline using a custom benchmark (`eval/eval_set.json`) measuring **Precision@3** (did the expected source document appear in the top 3 retrieved chunks?).

| Configuration | Precision@3 |
|---------------|-------------|
| Baseline (Dense Only) | TBD |
| Hybrid (Dense + BM25) | TBD |
| Hybrid + Re-ranking   | TBD |

*(Run `python eval/evaluate.py` to populate these metrics based on your actual data)*
