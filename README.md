# Personal RAG Chatbot (Fully Local)

A robust Retrieval-Augmented Generation (RAG) chatbot designed to answer questions over personal documents (PDFs, DOCX, Markdown) using a **100% local, free architecture**.

## Features & Architecture

This project implements an advanced retrieval pipeline built from scratch to demonstrate production-grade RAG concepts:

1. **Token-Aware Chunking:** Uses `tiktoken` to split text by tokens (not characters), preventing context window overflows.
2. **Hybrid Search (Dense + Sparse):**
   - **Dense:** `sentence-transformers` (`all-MiniLM-L6-v2`) + ChromaDB (HNSW).
   - **Sparse:** `rank_bm25` persistent index for exact keyword matching (acronyms, dates).
3. **Reciprocal Rank Fusion (RRF):** Fuses dense and sparse rankings without score normalization issues.
4. **Cross-Encoder Re-ranking:** Uses `ms-marco-MiniLM-L-6-v2` to jointly score query and candidate chunks, significantly improving top-K precision.
5. **Incremental Ingestion:** Uploads are hashed and indexed incrementally without rebuilding the entire vector store, saving compute resources.
6. **Local LLM Generation:** Uses Ollama (`llama3.2` 3B model) for free, local answer generation with inline citations.
7. **Query Routing:** Rewrites follow-up questions and routes between Small Talk, Local Knowledge, Summarization, and Live Web Search.

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

### Running the Application (Local Deployment)
This platform uses a decoupled architecture. You must run both the backend and frontend simultaneously.

1. **Start the FastAPI Backend:**
   ```bash
   uvicorn src.api.main:app --host 127.0.0.1 --port 8000
   ```
2. **Start the Streamlit Frontend (in a new terminal):**
   ```bash
   streamlit run app.py
   ```
3. Open `http://localhost:8501` to use the chatbot. You can upload documents directly through the UI, and they will be safely renamed, sized-checked, and incrementally ingested into the persistent vector database.

### Exposing a Public Demo
To share your local agent securely without renting cloud GPUs, you can use Cloudflare Tunnels or ngrok to expose your frontend:
```bash
cloudflared tunnel --url http://localhost:8501
# OR
ngrok http 8501
```
*(Note: Always secure your upload endpoints with authentication before sharing publicly.)*

## Design Decisions

### 1. Bi-Encoder vs. Cross-Encoder
Initial retrieval uses a fast Bi-Encoder (`all-MiniLM-L6-v2`) to narrow down thousands of chunks to the Top 10 in milliseconds using ChromaDB's HNSW graph. We then apply an expensive, highly accurate Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) only on those Top 10 chunks to re-rank and pick the best 3. This balances O(1) ANN search speed with O(N) Cross-Encoder precision.

### 2. Chunking Strategy
Chunks are roughly ~500 tokens with a ~50-token overlap, sized via `tiktoken`. We split recursively (Paragraphs -> Sentences) to ensure chunks contain coherent ideas and prevent "lost in the middle" effects during LLM generation.

### 3. Fully Local Stack
No paid APIs. We chose a 3B model (`llama3.2`) to comfortably fit within 8GB of system RAM alongside Python, Streamlit, and the two embedding models, without causing out-of-memory (OOM) errors.

## 4. Web Augmented RAG
The platform can dynamically route your queries to perform live internet searches (via DuckDuckGo) when your local documents don't have the answer!

## API Documentation
The FastAPI backend provides a Swagger UI for API exploration. Visit `http://localhost:8000/docs` in your browser.

## Evaluation

We evaluate the retrieval pipeline using a custom benchmark (`eval/eval_set.json`) measuring **Precision@3** (did the expected source document appear in the top 3 retrieved chunks?).

*(See `docs/EVALUATION.md` for our latest benchmarking results across Dense, BM25, and Hybrid setups)*
