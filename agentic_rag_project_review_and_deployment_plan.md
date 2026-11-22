# Agentic RAG Chatbot --- Code Review and Improvement Plan

## 1. Project Overview

This document summarizes the code-review findings and recommended
improvements for the **JVAISAG/Rag-chatbot** project.

The project is a local, modular RAG chatbot with:

-   Streamlit frontend
-   FastAPI backend
-   Ollama for local LLM inference
-   ChromaDB for vector storage
-   Sentence-transformer embeddings
-   BM25 sparse retrieval
-   Dense vector retrieval
-   Reciprocal Rank Fusion (RRF)
-   CrossEncoder reranking
-   Query routing
-   Document upload, deletion, ingestion, and chat functionality

The project is more advanced than a basic "upload a PDF and ask
questions" chatbot because it includes multiple retrieval strategies and
a modular pipeline.

------------------------------------------------------------------------

## 2. Overall Rating

### Current estimated rating: 7.5--8/10

This is a subjective student-portfolio rating based on the architecture
and implementation structure. It is not a substitute for a complete
end-to-end production audit with real documents, a running Ollama
instance, and benchmark results.

### Why the project is strong

The project demonstrates:

1.  Understanding of RAG beyond basic vector search.
2.  Modular separation of ingestion, retrieval, routing, generation, and
    API layers.
3.  Use of hybrid retrieval.
4.  Use of rank fusion and reranking.
5.  Local LLM execution through Ollama.
6.  A separate frontend and backend.
7.  An attempt to include automated tests.
8.  Practical document-management functionality.

### Suggested score breakdown

  ------------------------------------------------------------------------
  Area                               Estimated score Comments
  --------------------- ---------------------------- ---------------------
  Architecture and                            8.5/10 Modular frontend,
  engineering                                        API, pipeline, and
                                                     storage layers

  RAG sophistication                            9/10 Dense retrieval,
                                                     BM25, RRF, reranking,
                                                     and routing

  Practical usefulness                          8/10 Upload, deletion,
                                                     ingestion, chat
                                                     history, and
                                                     citations

  Testing                                       7/10 Tests exist, but
                                                     execution results and
                                                     coverage need
                                                     verification

  Production readiness                        6.5/10 Persistence,
                                                     security, deployment,
                                                     and reliability need
                                                     work

  Overall                                  7.5--8/10 Strong student
                                                     project with clear
                                                     improvement
                                                     opportunities
  ------------------------------------------------------------------------

------------------------------------------------------------------------

## 3. Architecture Summary

The intended architecture is:

``` text
                    ┌─────────────────────────┐
                    │      Streamlit UI       │
                    │ Chat / Upload / Sync    │
                    └────────────┬────────────┘
                                 │ REST HTTP
                                 ▼
                    ┌─────────────────────────┐
                    │      FastAPI API        │
                    │ Query / Upload / Index  │
                    │ Delete File              │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │       RAG Pipeline       │
                    │ Query Router             │
                    │ Ingestion                │
                    │ Hybrid Retrieval         │
                    │ Reranking                │
                    │ LLM Generation           │
                    └──────┬───────────┬───────┘
                           │           │
                           ▼           ▼
                 ┌─────────────┐ ┌─────────────┐
                 │  ChromaDB   │ │ ./data      │
                 │ Vector Store│ │ Documents   │
                 └─────────────┘ └─────────────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │ Ollama Local LLM │
                 └──────────────────┘
```

The architecture is suitable for a modular RAG system, but the deployed
implementation must be checked to ensure that the documented
FastAPI/Streamlit separation matches the actual runtime behavior.

------------------------------------------------------------------------

## 4. Main Strengths

### 4.1 Modular design

The project separates responsibilities across modules such as:

-   API server
-   RAG pipeline
-   Ingestion
-   Chunking
-   Embedding
-   ChromaDB storage
-   Dense retrieval
-   Sparse retrieval
-   RRF fusion
-   CrossEncoder reranking
-   Query routing
-   Generation

This makes the code easier to maintain, test, and extend.

The central pipeline orchestrator is preferable to placing all logic
inside the Streamlit application.

### 4.2 Hybrid retrieval

The project combines:

-   Dense semantic retrieval
-   Sparse BM25 keyword retrieval
-   Reciprocal Rank Fusion
-   Optional CrossEncoder reranking

This is a strong design because dense retrieval is good at semantic
similarity while BM25 can perform better for exact keywords, names,
identifiers, and technical terms.

### 4.3 Reciprocal Rank Fusion

RRF combines rankings from multiple retrieval systems. A typical formula
is:

``` text
RRF score(d) = Σ 1 / (k + rank_i(d))
```

where:

-   `d` is a document or chunk
-   `rank_i(d)` is the rank of the document in retriever `i`
-   `k` is a smoothing constant

This is a useful way to combine dense and sparse retrieval without
requiring their raw scores to be directly comparable.

### 4.4 CrossEncoder reranking

The project retrieves candidate chunks and then reranks them using a
CrossEncoder.

This is a strong retrieval architecture:

``` text
Query
  ↓
Dense + Sparse Candidate Retrieval
  ↓
RRF Fusion
  ↓
CrossEncoder Reranking
  ↓
Top Context
  ↓
LLM Generation
```

Reranking can improve relevance because the CrossEncoder evaluates the
query and candidate text together.

### 4.5 Local LLM execution

Ollama provides local inference and avoids per-request hosted-LLM API
costs.

Advantages:

-   No external LLM API bill
-   Better control over data locality
-   Easier experimentation with local models
-   Useful discussion topic for model-size and hardware tradeoffs

Tradeoffs:

-   Requires enough RAM/CPU/GPU
-   Slower on weak hardware
-   Difficult to host continuously on free cloud tiers
-   Public access consumes local system resources

### 4.6 Testing effort

The project includes tests covering areas such as:

-   API endpoints
-   BM25 retrieval
-   RRF
-   Query routing
-   Citations
-   Generation
-   Chunking
-   Reranking
-   Web search

The next step is to run the full test suite and report the results in
the README or CI pipeline.

------------------------------------------------------------------------

## 5. Important Issues to Fix

## 5.1 BM25 index is not persistent

### Problem

The BM25 index is stored in memory. It is rebuilt during ingestion, but
a fresh application process may start without a populated sparse index.

This can cause hybrid retrieval to behave differently after a restart.

### Impact

-   Sparse retrieval may return no results after restart.
-   Hybrid retrieval may effectively become dense-only.
-   Results may vary between a fresh run and a restarted run.
-   The system may appear to work locally but fail after deployment.

### Recommended fix

Choose one of these approaches:

#### Option A: Rebuild BM25 automatically at startup

1.  Load the existing document/chunk metadata.
2.  Reconstruct the BM25 corpus.
3.  Build the BM25 index during application startup.
4.  Mark the index as ready only after initialization completes.

#### Option B: Persist the BM25 corpus and metadata

Persist:

-   Chunk IDs
-   Chunk text
-   Source file names
-   Metadata
-   Tokenized corpus or enough information to rebuild it

Then reconstruct the BM25 index on startup.

#### Option C: Use a persistent search engine

For larger deployments, consider a search engine or vector database that
supports both dense and sparse retrieval.

------------------------------------------------------------------------

## 5.2 Destructive shutdown behavior

### Problem

The FastAPI lifespan/shutdown behavior appears to delete the data
directory and reset ChromaDB during shutdown.

### Why this is dangerous

A normal shutdown can happen during:

-   Deployment
-   Server restart
-   Process crash recovery
-   Machine reboot
-   Cloud instance replacement
-   Manual maintenance

If shutdown deletes the data, the application can lose:

-   Uploaded documents
-   ChromaDB vectors
-   Ingestion state
-   Metadata
-   Potentially the entire knowledge base

### Recommended fix

Remove destructive cleanup from the shutdown handler.

Shutdown should:

-   Close resources
-   Stop background tasks
-   Flush logs
-   Release connections

It should not delete persistent application data.

If a reset operation is needed, implement a separate administrative
command or endpoint with:

-   Authentication
-   Explicit confirmation
-   Logging
-   Optional backup
-   Restricted access

Example conceptual endpoint:

``` text
POST /api/v1/admin/reset
```

This endpoint should never be publicly accessible without strong
protection.

------------------------------------------------------------------------

## 5.3 File upload security

### Problem

The upload endpoint writes uploaded files using the supplied filename.
This can create security risks if filenames are not sanitized and
validated.

### Risks

-   Path traversal
-   Unexpected file extensions
-   Oversized files
-   Malicious or malformed documents
-   Resource exhaustion
-   Untrusted content entering the retrieval system
-   Unauthorized document replacement

### Recommended fix

Implement all of the following:

1.  Generate a server-side unique filename.
2.  Do not trust the client-provided filename.
3.  Validate allowed extensions.
4.  Enforce a maximum upload size.
5.  Validate MIME type where practical.
6.  Store uploads outside the public static directory.
7.  Reject unsupported or malformed files.
8.  Add authentication for upload, delete, and indexing operations.
9.  Log upload metadata.
10. Consider scanning uploaded files before processing.

Allowed extensions could include:

``` text
.pdf
.docx
.txt
.md
```

The final list should match the actual loaders supported by the project.

------------------------------------------------------------------------

## 5.4 Full index rebuilds are expensive

### Problem

The current ingestion flow appears to rebuild the whole index when files
are added or deleted.

A rebuild may involve:

1.  Deleting the existing ChromaDB collection.
2.  Loading all documents.
3.  Splitting all documents into chunks.
4.  Recomputing all embeddings.
5.  Rebuilding BM25.
6.  Recreating the collection.

### Impact

-   Slow ingestion
-   Higher CPU/GPU usage
-   Increased latency
-   Unnecessary recomputation
-   Poor scalability as the dataset grows

### Recommended fix

Implement incremental ingestion.

For each file, track:

-   File ID
-   Original filename
-   File hash
-   Upload time
-   Chunk IDs
-   Embedding model
-   Processing status

When a new file is uploaded:

1.  Compute its hash.
2.  Check whether it already exists.
3.  Process only the new file.
4.  Add its chunks to ChromaDB.
5.  Update the sparse index.

When a file is deleted:

1.  Find all chunk IDs belonging to that file.
2.  Delete only those chunks from ChromaDB.
3.  Remove the file from the BM25 corpus.
4.  Rebuild or update the sparse index.

------------------------------------------------------------------------

## 5.5 API errors may expose internal details

### Problem

Returning the raw exception string to the client can reveal internal
information.

Possible leaked information includes:

-   File paths
-   Stack-related details
-   Model names
-   Database paths
-   Internal implementation details
-   Dependency errors

### Recommended fix

Return a generic response to the client:

``` json
{
  "detail": "The chatbot could not process your request."
}
```

Log the detailed exception on the server side.

Use structured logging with:

-   Timestamp
-   Request ID
-   Endpoint
-   Error type
-   Stack trace
-   User/session identifier where appropriate

Do not expose secrets or sensitive document content in logs.

------------------------------------------------------------------------

## 5.6 Deployment mismatch to resolve

The architecture document describes:

-   Streamlit frontend
-   FastAPI backend
-   Separate REST communication

The repository documentation may also describe direct Streamlit
execution.

Before deployment, confirm:

1.  Is FastAPI actually the production backend?
2.  Does Streamlit call FastAPI through `requests`?
3.  Are all API routes consistent between frontend and backend?
4.  Is the backend started independently?
5.  Is the frontend configured using an environment variable for the
    backend URL?
6.  Are upload, indexing, and deletion operations handled by FastAPI?
7.  Are local development URLs separated from production URLs?

The README and architecture diagram should describe the same real
runtime architecture.

------------------------------------------------------------------------

## 6. Deployment Plan for a Free Public Demo

## 6.1 Recommended first deployment

For a genuinely local Ollama model, the most practical free
demonstration is:

``` text
Your laptop:
    Ollama
    Embedding model
    CrossEncoder
    ChromaDB
    FastAPI
    Streamlit

          ↓

Secure tunnel:
    Cloudflare Tunnel or ngrok

          ↓

Public users
```

### Why this approach is practical

-   Keeps the existing local Ollama setup.
-   Avoids cloud GPU costs.
-   Requires minimal architectural changes.
-   Allows you to demonstrate the full pipeline.
-   Works with your existing local documents and vector database.

### Limitations

-   Your laptop must remain powered on.
-   Ollama must remain running.
-   The tunnel must remain active.
-   Performance depends on your hardware.
-   Public users consume your CPU, RAM, and GPU.
-   It is not a production-grade always-on deployment.

------------------------------------------------------------------------

## 6.2 Local startup sequence

### Start Ollama

Example:

``` powershell
ollama serve
```

In another terminal, ensure the models are available:

``` powershell
ollama list
```

If needed:

``` powershell
ollama pull llama3.2
ollama pull nomic-embed-text
```

Use the exact model names configured in the project.

### Start FastAPI

From the project root:

``` powershell
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Adjust the module path if the actual project uses a different entry
point.

### Test the API

Open:

``` text
http://127.0.0.1:8000/docs
```

Test:

-   Health endpoint
-   Query endpoint
-   Upload endpoint
-   Index endpoint
-   File deletion endpoint

### Start Streamlit

In another terminal:

``` powershell
streamlit run app.py
```

Confirm that the frontend points to the FastAPI server.

------------------------------------------------------------------------

## 6.3 Public tunnel

### Cloudflare Tunnel

A temporary tunnel can forward the local FastAPI server:

``` powershell
cloudflared tunnel --url http://localhost:8000
```

Cloudflare will provide a public HTTPS URL.

### ngrok

Alternatively:

``` powershell
ngrok http 8000
```

Use the generated HTTPS URL as the public API address.

### Important

A tunnel exposes the API. It does not automatically add:

-   Authentication
-   Rate limiting
-   Request validation
-   File upload protection
-   Abuse prevention

Do not share an unprotected upload/delete/index API widely.

------------------------------------------------------------------------

## 7. Suggested Configuration

Create a `.env.example` file:

``` dotenv
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.2
EMBED_MODEL=nomic-embed-text

CHROMA_PATH=./vectorstore
CHROMA_COLLECTION=documents
DATA_DIR=./data

BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000

MAX_UPLOAD_MB=10
TOP_K=5
```

Use the actual names and configuration keys expected by the codebase.

Do not commit the real `.env` file.

Recommended `.gitignore` entries:

``` gitignore
.env
.venv/
__pycache__/
*.pyc
vectorstore/
data/
.pytest_cache/
.coverage
```

Only ignore `data/` and `vectorstore/` if the project does not
intentionally version a small demo dataset.

------------------------------------------------------------------------

## 8. Security Checklist

Before exposing the application publicly:

-   [ ] Remove destructive cleanup from shutdown.
-   [ ] Keep ChromaDB persistent.
-   [ ] Back up source documents.
-   [ ] Generate safe server-side upload filenames.
-   [ ] Validate file extensions.
-   [ ] Enforce upload size limits.
-   [ ] Add authentication to upload endpoints.
-   [ ] Add authentication to delete endpoints.
-   [ ] Add authentication to index/rebuild endpoints.
-   [ ] Add rate limiting to query requests.
-   [ ] Limit query length.
-   [ ] Limit chat-history size.
-   [ ] Do not expose Ollama port `11434` directly.
-   [ ] Return generic API errors.
-   [ ] Log detailed errors only on the server.
-   [ ] Avoid logging document contents or secrets.
-   [ ] Restrict administrative operations.
-   [ ] Validate and sanitize metadata.
-   [ ] Protect the public tunnel URL where possible.

------------------------------------------------------------------------

## 9. Evaluation Plan

The README should contain real evaluation results instead of only
listing metrics as `TBD`.

### Retrieval metrics

Consider measuring:

-   Precision@k
-   Recall@k
-   Hit Rate@k
-   MRR
-   nDCG
-   Context precision
-   Context recall

Compare at least these configurations:

1.  Dense retrieval only
2.  BM25 only
3.  Dense + BM25 with RRF
4.  Dense + BM25 + CrossEncoder reranking

### Example evaluation table

  Configuration         Precision@3   Recall@k   MRR Notes
  ------------------- ------------- ---------- ----- --------------------------
  Dense only                    TBD        TBD   TBD Baseline
  BM25 only                     TBD        TBD   TBD Keyword baseline
  Hybrid + RRF                  TBD        TBD   TBD Combined retrieval
  Hybrid + reranker             TBD        TBD   TBD Final retrieval pipeline

Do not fill these values with invented numbers. Run the evaluation and
report measured results.

### Generation evaluation

Evaluate:

-   Answer correctness
-   Faithfulness to retrieved context
-   Citation correctness
-   Citation completeness
-   Hallucination rate
-   "I don't know" behavior when context is insufficient

### Performance evaluation

Measure:

-   Average query latency
-   p50 latency
-   p95 latency
-   Embedding time
-   Retrieval time
-   Reranking time
-   LLM generation time
-   Memory usage
-   Concurrent-user behavior

------------------------------------------------------------------------

## 10. Testing Plan

Run the full test suite before deployment.

Suggested commands:

``` powershell
pytest -q
```

For coverage:

``` powershell
pytest --cov=src --cov-report=term-missing
```

Add tests for:

### API

-   Health endpoint
-   Valid query
-   Empty query
-   Oversized query
-   Invalid file type
-   Oversized upload
-   Missing collection
-   Failed Ollama request
-   Failed ChromaDB request
-   Unauthorized administrative operation

### Ingestion

-   PDF loading
-   DOCX loading
-   TXT loading
-   Markdown loading
-   Chunk overlap
-   Empty document
-   Corrupted document
-   Duplicate file
-   File deletion

### Retrieval

-   Dense retrieval
-   BM25 retrieval
-   RRF fusion
-   Reranking
-   No-result retrieval
-   Duplicate chunks
-   Metadata preservation

### Routing

-   Small talk
-   Web search
-   Direct knowledge
-   Summarization
-   Invalid router output
-   LLM routing failure

### Persistence

-   Restart application
-   Rebuild BM25 on startup
-   ChromaDB persistence
-   File deletion persistence
-   Recovery after failed ingestion

------------------------------------------------------------------------

## 11. Recommended Improvement Roadmap

### Phase 1 --- Correctness and safety

1.  Remove destructive shutdown cleanup.
2.  Fix BM25 persistence or startup rebuilding.
3.  Add upload validation.
4.  Add safe filenames.
5.  Add generic API error responses.
6.  Add limits to query and upload sizes.

### Phase 2 --- Reliability

1.  Add startup health checks.
2.  Add Ollama availability checks.
3.  Add ChromaDB readiness checks.
4.  Add structured logging.
5.  Add request IDs.
6.  Add retry handling for transient failures.
7.  Add proper handling for empty retrieval results.

### Phase 3 --- Retrieval quality

1.  Build a labeled evaluation dataset.
2.  Measure dense retrieval.
3.  Measure BM25.
4.  Measure RRF.
5.  Measure CrossEncoder reranking.
6.  Tune chunk size and overlap.
7.  Tune `top_k`.
8.  Compare embedding models.
9.  Report results in the README.

### Phase 4 --- Performance and scalability

1.  Implement incremental ingestion.
2.  Avoid rebuilding the entire index after every file operation.
3.  Cache embeddings where appropriate.
4.  Cache repeated queries where appropriate.
5.  Add asynchronous background ingestion.
6.  Measure latency and memory usage.
7.  Add concurrency tests.

### Phase 5 --- Deployment

1.  Run the entire stack locally.
2.  Deploy a temporary tunnel demo.
3.  Add authentication and rate limiting.
4.  Document startup commands.
5.  Add a demo video or screenshots.
6.  Consider a cloud deployment only after solving the local Ollama
    hosting problem.

------------------------------------------------------------------------

## 12. Resume-Ready Project Description

### Short version

**Agentic RAG Chatbot \| Python, FastAPI, Streamlit, ChromaDB, Ollama**

-   Built a modular local RAG chatbot with dense and BM25 sparse
    retrieval, Reciprocal Rank Fusion, and CrossEncoder reranking.
-   Implemented query routing for small talk, web search, direct
    knowledge retrieval, and summarization.
-   Developed a FastAPI backend and Streamlit frontend for document
    upload, ingestion, deletion, and conversational querying.
-   Integrated ChromaDB for persistent vector storage and Ollama for
    local LLM inference.
-   Added automated tests for retrieval, routing, ingestion, API
    behavior, and generation.

### Stronger version after improvements

-   Built and evaluated a hybrid RAG system combining dense retrieval,
    BM25, RRF, and CrossEncoder reranking.
-   Improved retrieval quality through a labeled benchmark comparing
    dense, sparse, hybrid, and reranked configurations.
-   Implemented persistent document indexing, incremental ingestion,
    safe file handling, and authenticated API operations.
-   Deployed a public demonstration with FastAPI, Streamlit, ChromaDB,
    and local Ollama inference.

Only include claims such as "improved retrieval quality," "deployed," or
"authenticated" after you have actually implemented and measured them.

------------------------------------------------------------------------

## 13. Final Assessment

This is a strong student project with good potential for:

-   AI/ML internships
-   Backend engineering internships
-   Software engineering roles
-   RAG and LLM application projects
-   Research-oriented discussions about retrieval quality

The most impressive parts are:

1.  Hybrid dense and sparse retrieval.
2.  RRF fusion.
3.  CrossEncoder reranking.
4.  Modular pipeline design.
5.  Local LLM integration.
6.  Separation of frontend and backend.

The most important weaknesses to fix are:

1.  Destructive shutdown behavior.
2.  BM25 persistence.
3.  Upload security.
4.  Full index rebuilding.
5.  Lack of measured evaluation results.
6.  Deployment and public-access security.

### Final rating

**Current estimated rating: 7.5--8/10**

After fixing persistence and security issues, adding real retrieval
benchmarks, and demonstrating a stable deployment, the project could
reasonably become a **9/10-level student portfolio project**.
