# Current Architecture

## Overview
The existing project is a local RAG chatbot with support for hybrid retrieval, reranking, and document ingestion (PDF, DOCX, TXT, MD). It is built using Streamlit, ChromaDB, SentenceTransformers, and Ollama.

## Flow
```text
User Query
   ↓
Query Condensation (Llama 3.2 via Ollama)
   ↓
Dense Retrieval (ChromaDB)
   +
BM25 Retrieval (rank_bm25 - in memory)
   ↓
RRF (Reciprocal Rank Fusion - custom)
   ↓
Cross Encoder Reranking (ms-marco-MiniLM-L-6-v2)
   ↓
Context Construction
   ↓
Local LLM (Llama 3.2 via Ollama)
   ↓
Citations (Regex matching [N])
   ↓
Answer
```

## Current Strengths
- **Modular pipeline**: Code is split neatly into `ingest.py`, `chunk.py`, `store.py`, `embed.py`, `retrieve.py`, and `generate.py`.
- **Advanced Retrieval**: Hybrid search, RRF, and cross-encoder reranking are already implemented.
- **Local Privacy**: Uses `ollama` and `sentence-transformers` for a fully local pipeline.
- **Document Support**: Existing parsing for PDF, DOCX, and Markdown/TXT.
- **Query Condensation**: Basic follow-up rewriting is implemented.

## Current Weaknesses
- **BM25 In-Memory**: BM25 index is built in-memory and re-calculated from raw chunks, which won't scale.
- **Citations**: Citations rely on basic regex extraction (`\[\d+\]`) from the generated answer and fallback to all chunks if the model fails to cite.
- **Chunking Strategy**: Chunking uses a naive custom text splitter rather than a robust library solution.
- **Tightly Coupled UI**: Streamlit UI code directly interacts with file system and model logic.
- **Evaluation**: The current `evaluate.py` only tests Precision@3 on a hardcoded, 2-question JSON file, completely skipping MRR/Recall/NDCG.

## Technical Debt & Duplicate Code
- **Metadata Management**: Ensuring metadata types are strictly basic types in `store.py` is somewhat brittle.
- **Overlapping Concepts**: The Streamlit file upload directly writes to a `data` dir, requiring a two-step process ("Save Uploaded Files" then "Build Index").
- **Missing Async**: Blocking UI for slow processes (ingestion, LLM generation).

## Missing Tests
- No unit tests or integration tests exist in the repository (e.g., `pytest` is missing). Only a minimal `if __name__ == "__main__":` block is at the bottom of some files.

## Missing Evaluation
- Actual metrics like Recall@K, MRR, NDCG are missing.
- Answer quality evaluations (Faithfulness, Context Relevance, Answer Relevance) are not implemented.
- The evaluation dataset `eval_set.json` is tiny (2 questions) and inadequate.

## Components to Preserve
- **Core RAG Logic**: The existing implementation of RRF, BM25 logic, query condensation, and cross-encoder scoring are functioning and should be retained/refactored rather than rewritten from scratch.
- **Vector DB Choice**: ChromaDB is adequate and its usage should be preserved.
- **Local Model Usage**: The dependency on Ollama and sentence-transformers is a strong architectural choice that fits the goals.
