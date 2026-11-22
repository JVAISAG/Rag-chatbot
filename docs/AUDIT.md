# Baseline audit — 1 November 2026

## Corrected behavior

| Area | Correction |
|---|---|
| Installation | Embedding source is no longer ignored by Git; runtime dependencies are declared and pinned; dev dependencies are separate. |
| Startup | Importing the API no longer loads real models; a lazy pipeline factory enables isolated testing. |
| Uploads | Validate names, types, file count, per-file and batch sizes; reject unreadable documents; report partial batch results accurately. |
| Indexing | Embed only changed uploads; skip identical replacements; preserve original-name mappings; remove obsolete chunks. |
| Deletion | Remove saved files and dense/sparse records, including the final document; rebuilds do not restore deleted uploads. |
| Failure recovery | Restore previous records on recoverable writes, restore staged files on failures, and reconcile staged files on startup. |
| Sparse search | Derive BM25 from the persisted collection; remove unsafe pickle loading; fix tiny-collection and punctuation behavior. |
| Chunking | Apply real overlap; enforce encoder input limits using its tokenizer; handle long unbroken text and Unicode. |
| Parsing | Preserve PDF pages, include DOCX tables, accept UTF-8 BOMs, and surface malformed/empty document errors. |
| Retrieval settings | Avoid shared reranker mutation and allow dense-only reranking; handle empty collections. |
| Generation | Bound context and output; set timeouts; surface model outages as 503; reject missing/out-of-range citations. |
| Web search | Replace the deprecated provider package with maintained `ddgs`, keep an explicit DuckDuckGo backend, reject invalid evidence, and surface provider errors as 503. |
| Interface | Preserve citation numbering/names across reruns; use explicit saved-document deletion and bounded history/requests. |
| Lifecycle | Close Chroma and HTTP clients without deleting persisted data. |
| Evaluation | Isolate benchmark indexes; use exact source matches; retain sparse tails; execute requested reranking and report only measured outcomes. |
| Maintenance | Add regression tests and a GitHub Actions workflow. |

## Validation scope

The regression suite exercises real Chroma persistence, HTTP endpoints through
FastAPI's test client, and Streamlit's AppTest. Model behavior is substituted for
deterministic tests. Checks include restart persistence, last-file deletion,
shorter replacements, duplicate uploads, failed-write rollback, interrupted staging,
concurrent uploads, upload validation, bounded chunking/context, citation metadata,
and interface reruns.

## Results

- **101 tests passed**, with no warnings, in the final local run (29.03 seconds).
- `python -m pip check` passed. Python compilation and `git diff --check` passed.
- Both real CPU retrieval models were prepared and loaded successfully. Their
  caches are under the ignored `.cache/` directory.
- The real retrieval benchmark completed for dense, BM25, interleaved hybrid,
  RRF hybrid, and RRF plus reranking. On 12 questions over three synthetic files,
  dense top-one hit rate was 11/12 and reranked hybrid was 12/12. This is a small
  functional smoke benchmark, not evidence of general answer quality. See
  [EVALUATION.md](EVALUATION.md) for all measured results.
- A live public web-search smoke query returned two usable results after the
  provider upgrade. No private document text was sent in that check.
- The optional API test-client dependency was updated to the supported `httpx2`
  package, eliminating the previous deprecation warning.
- The local Ollama service was not reachable at `http://127.0.0.1:11434`.
  Live answer generation and routing could therefore not be verified. Deterministic
  tests cover their behavior and failure handling, but do not replace this check.
- Tests and benchmarks used temporary databases; the application's existing
  document folder and Chroma collection were not rebuilt or reset during the audit.
- The pre-existing untracked review/deployment-plan document was left unchanged.

## Remaining boundaries

- A green regression suite does not guarantee no future defects or correct LLM answers.
- Citation validation checks IDs and metadata, not semantic entailment.
- Context accounting for Ollama is approximate; the evidence tokenizer differs.
- Full-document summarization, OCR, web-page extraction, authentication, rate limits,
  per-user data isolation, and distributed indexing are not implemented.
- File/database operations are not one atomic crash transaction; rollback itself
  can fail under disk failure. Back up data before upgrades.
- The local API must run with one worker. Public multi-user deployment needs a
  separate security and concurrency design.
- GitHub Actions has been configured locally; remote CI is not claimed to have run.
