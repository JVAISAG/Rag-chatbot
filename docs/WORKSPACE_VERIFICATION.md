# Workspace verification

## Local release — 22 November 2026

The implemented workflow now includes accounts, private collections, versioned
file/article imports, reader/originals, scoped hybrid search and cited Q&A,
checkpointed summaries, descriptive comparisons, notes, and Markdown export.
Source deletion and collection detachment mask unavailable saved evidence;
notes retain the user's text. Notes reject stale versions, and the UI protects
unsaved edits when closing, switching collections, or signing out.

- The final Python regression run passed **430 tests**, with eight opt-in
  PostgreSQL checks skipped. Dependency validation (`pip check`) passed.
- A separate disposable-database run passed **nine PostgreSQL/pgvector checks**,
  including those eight checks plus the migration graph. It covers concurrent
  updates, source scopes, all retrieval modes, saved research, and migrations.
  The final run also verifies source tracking defaults, protected downgrades,
  preserved reading progress, quoted-answer persistence and masking, and the
  30-second retry delay (nine checks in 99.01 seconds).
- The legacy Streamlit test initially exceeded its ten-second cold-start limit.
  Its wait allowance is 30 seconds, including reruns; behavior assertions
  remain unchanged. A later concurrent inference run also exceeded that limit.
  With Ollama stopped, the complete suite passed. The final completion run passed
  all 430 tests in 71.25 seconds without further timeout changes. Run memory-heavy
  verification stages sequentially on this host.
- The frontend production build passed compilation, TypeScript, and static pages.
- All **six browser scenarios passed** against a disposable database and real
  API: articles, document upload/reader, comparisons/notes/export, account
  isolation, mobile layout, and loading-error recovery. The research check also
  confirms navigation cancellation preserves a draft and editing is disabled
  while a save is pending. The earlier mobile timeout did not reproduce in the
  isolated rerun or complete suites. The latest suite passed in 27.8 seconds and
  also checks side-by-side/stacked reading panes, quoted answers, visible timing,
  locked submission/metadata fields, source tags, reading progress, and a
  maximum-length unbroken tag on mobile.
- Eight focused backend checks passed after preserving existing note attachments
  when a source is detached. New attachments still require current membership;
  unavailable retained evidence does not prevent editing the user's note.
- Migration `20261121_01` is applied to the real workspace. It adds source tags
  and reading progress; existing sources receive empty tags and unread status.
  All three sources and their original files were preserved. Changed revisions
  reset progress only on successful publication; unchanged/failed updates retain
  it. Metadata saves can reject stale revision snapshots. Readiness and the normal
  worker reject missing/outdated migration heads. `alembic check` reports no
  differences between the final models and database.
- Real original-model (`llama3.2`, 3B) summary and Q&A checks passed using the
  verified NVIDIA Compose override. See `PERFORMANCE_NOTES.md` for the measured
  37.46-second one-passage summary and the smaller model's factual failures.
- The final Qwen3 4B standalone answer-worker check reproduced batch size 64
  and 16 epochs with a saved supporting reference. A real three-passage
  `summary-v3` map/synthesis check completed in 23.33 seconds warm and retained
  batch size 64, 90 percent accuracy, and small sample size with references to
  the correct original passages. The new guard prevents synthesis from erasing
  an entire reported dimension; it does not prove all facts are retained.
- Sustained replay initially exposed a CUDA failure and old-prompt RAM retention.
  The pinned runner now confirms prompt caching and context checkpoints are
  disabled. All 37 replay cases then completed; GPU offloading was verified at
  2048 and 4096 contexts. Resource findings and cold-load costs are recorded in
  `PERFORMANCE_NOTES.md`.
- The full real-model pipeline passed again on 22 November with the final
  Qwen3 4B model, `qa-v4`, and migration `20261121_01`: upload, extraction,
  real embeddings, BM25/pgvector/RRF/reranking, cited answer, follow-up, empty
  scope, and cross-account not-found responses. Both expected values (batch size
  64 and 16 epochs) were preserved. Its temporary database and originals were
  removed. The original-model run used a 4096-token context at 20% CPU / 80% GPU;
  the final model uses the verified 2048-token GPU profile.
- All four retrieval modes completed 34 answerable development cases and 29
  answerable validation cases. The separate validation corpus has distinct
  fictional sources and was frozen before its first model run. Fingerprinted
  retrieval reports prevent replay against the wrong corpus.
- All 69 `qa-v4` answer cases completed and were reviewed against their passages.
  Development: 31 supported generated answers, two supported exact excerpts,
  three appropriate abstentions, and one false refusal (q26). Validation: 29
  supported answers and three appropriate abstentions. The dataset-name typo
  is fixed; both hostile-source instructions were ignored. Exact excerpts are
  labeled as potentially partial. `eval/workspace_answer_review.json` binds
  engineering judgements to the final reports. No independent human grading or
  real-paper scientific accuracy is established; see `EVALUATION.md`.
- A private live database/files backup was created and restored into a separate
  generated database. Table counts, migration version, and file SHA-256 checksums
  matched. The restore test database and files were removed. The backup remains
  private under `.cache/` and is excluded from version control.
  The pre-tracking backup and a fresh `20261121_01` backup both passed separate
  restore checks during the completion pass. Their temporary databases/files
  were removed, and the private backups were retained.
- The abandoned database and matching synthetic originals from the interrupted
  benchmark were identified by their synthetic user and storage keys, then removed.
- CI now defines regression, PostgreSQL/pgvector, and frontend jobs. Remote
  GitHub Actions execution has not been performed in this session.
- Final startup checks passed for the normal frontend on port 3000, the API
  readiness endpoint on 8001, and the same-origin readiness proxy (all HTTP 200).
  Unauthenticated account access through the proxy returned 401. The worker
  heartbeat was fresh and matched the configured database; the final model was
  installed. Existing originals still matched the private backup checksums, and
  no notes had lost their collection reference. The normal services were left
  running; disposable verification databases were removed.

The [release runbook](LOCAL_RELEASE.md) contains reproducible startup, verification,
and backup/restore commands. Model-generated claims still require review against
their cited passages. This is a verified local demonstration, not a production
service or a guarantee that arbitrary generated answers are correct.

## Historical Q&A milestone — 14 November 2026

The local Docker setup and cited Q&A milestone were checked with real Ollama,
embeddings, reranking, and PostgreSQL. This records a functional check, not a
general answer-quality or performance benchmark.

## Configuration

- Ollama 0.40.16 in Docker, using the image digest pinned in
  `compose.workspace.yaml` and CPU inference.
- `llama3.2:latest`, manifest
  `sha256:a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`.
- `pgvector/pgvector:0.8.7-pg16`, workspace migration `20261114_01`.
- Embeddings: `all-MiniLM-L6-v2`; reranking:
  `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- Both Docker ports are bound to loopback. Docker's data disk is on D:.

## Results

- The default Python suite passed **294 tests**; six PostgreSQL checks are
  intentionally skipped without their opt-in environment setting.
- A separate isolated run passed **7 database/migration checks**, including
  those six checks. One migration-graph check overlaps the default suite.
- The frontend production build passed, including TypeScript and static-page
  generation.
- The real generation smoke check passed with saved evidence and valid citation
  numbers.
- The full pipeline passed: account creation and sign-in, text upload,
  extraction, real embeddings and chunk publication, BM25 plus pgvector search,
  RRF and real cross-encoder reranking, a generated answer, a follow-up,
  empty-collection handling, and cross-account not-found responses.
- The synthetic document stated a batch size of 64 and 16 training epochs.
  The generated answer reproduced both settings with `[1]` references; the
  follow-up reproduced 16 epochs with a supporting reference.
- Test databases and synthetic file storage were removed afterward. The live
  workspace library was not populated with test accounts or documents.
- The running frontend, API readiness check, same-origin API proxy, and Ollama
  model-list endpoint returned successful responses. An unauthenticated account
  request through the frontend proxy correctly returned `401`.
- The verification CLI refused a remote database configuration and Python
  optimization before creating any test data.

The first live check exposed a prompt issue: the model omitted citation markers
or used a form such as `[1:64]`. The `qa-v2` prompt now enumerates the exact
allowed markers, and the worker records that version before generation. Citation
validation remains strict, with one repair attempt and a safe unsupported-answer
result when validation fails. Tests also check that the additional instructions
leave context space for the system prompt and output.

## Repeat the checks

Follow [the local setup guide](WORKSPACE_DATABASE.md), then run from the project
root:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe scripts/verify_workspace.py integration
.\venv\Scripts\python.exe scripts/smoke_workspace_ollama.py
.\venv\Scripts\python.exe scripts/verify_workspace.py live
```

The last two commands require local Ollama and the configured model. The full
pipeline check also needs cached retrieval models. The verification script only
creates generated temporary databases on a local PostgreSQL server; its database
role needs permission to create databases.

These checks do not establish semantic correctness for arbitrary questions.
The reviewed evaluation corpus, URL ingestion, source lifecycle operations,
analysis tools, and other unfinished plan items remain separate work.
