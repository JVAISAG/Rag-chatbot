# Local research workspace runbook

The workspace supports private document and public article imports, versioned
refresh/replacement, hybrid search, cited conversations, revision-pinned summaries,
descriptive source comparisons, editable notes, and Markdown export. Generated
claims still require review against their passages. This is a local demonstration,
not an assertion of production readiness or universal answer accuracy.

## Start from a clean checkout

1. Create a Python 3.12 virtual environment and install `requirements-dev.txt`.
2. Copy `.env.example` to `.env`, choose a private database password, and retain
   `WORKSPACE_COOKIE_SECURE=false` only for local HTTP. Keep `.env` private.
3. Start PostgreSQL and prepare the models:

```powershell
docker compose -f compose.workspace.yaml up -d --wait --wait-timeout 120 postgres
.\venv\Scripts\python.exe -m alembic -c workspace.alembic.ini upgrade head
.\venv\Scripts\python.exe scripts/prepare_models.py --embeddings --reranker
```

Choose the Ollama configuration matching the machine. CPU-only:

```powershell
docker compose -f compose.workspace.yaml --profile inference up -d --wait --wait-timeout 120 ollama
```

For a machine with verified NVIDIA Docker support:

```powershell
docker compose -f compose.workspace.yaml -f compose.workspace.gpu.yaml --profile inference up -d --wait --wait-timeout 120 ollama
```

The GPU override only adds device access. It preserves the original model volume,
database, and model selection. Confirm actual offloading with `ollama ps`; device
detection alone does not establish acceleration. Download the configured model:

```powershell
docker compose -f compose.workspace.yaml exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
```

The release profile uses a 2048-token Q&A context, prompt batch size 128, a
300-second cold-start timeout, and 15-minute model retention. On the tested
RTX 3050 Laptop 4 GB GPU, `OLLAMA_GPU_LAYERS=99` placed this model fully on the
GPU. Leave that setting unset for CPU/automatic placement or unverified hardware.
Longer summary synthesis contexts may use a different CPU/GPU split.
Compose disables the runner's host cache of old prompts and context checkpoints,
and permits one loaded model and one concurrent request. This avoids the pinned
runner's 8 GB old-prompt cache default on small hosts. The model remains loaded
for warm requests; this cache is separate from BM25. See the measured findings
in `PERFORMANCE_NOTES.md` before increasing `WORKSPACE_OLLAMA_CACHE_RAM_MB`.

Run the API and one worker in separate terminals:

```powershell
.\venv\Scripts\python.exe -m uvicorn src.workspace.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers
.\venv\Scripts\python.exe -m src.workspace.jobs
```

In the frontend directory, install with `npm ci`, build with `npm run build`, and
run `npm start`. Open http://127.0.0.1:3000/. Keep the ports bound to loopback.
API readiness and the worker require migration `20261121_01`. Apply migrations
before restarting updated code; liveness alone does not establish schema readiness.

## Demonstrate the workflow

Create an account and collection. Import a paper and public articles, wait for
indexing, read passages and originals, ask a cited question, and generate a summary
for each source. **Read text** opens extracted pages beside the questions on
desktop; the panes stack on mobile. **Processing times** on an answer shows its
initial queue wait, retrieval/rewrite stage, and latest generation/evidence checks.
Cold loading can dominate these stages. Queue time is preserved across retries;
the stage figures are not an end-to-end browser latency measurement.
Open **Research comparisons and notes**, refresh the list, select
2–5 summaries from different sources, and save a comparison. Write a note, attach
selected findings/comparisons, save, and export Markdown.

**Edit details** also saves source tags and reading progress across all of that
account's collections. Tags allow up to 20 labels of 32 characters; duplicate
labels ignore case. A changed file/article revision becomes unread only after
successful publication. Unchanged or failed updates preserve progress, and tags
are retained. A form opened against an older revision returns a conflict rather
than marking changed content read; reopen details before saving again.

Comparisons preserve each source's result and evidence instead of inventing a
cross-dataset performance ranking. Missing and unavailable evidence is labeled.
Refresh does not rewrite saved summary revisions. Deletion removes source access
and marks its saved evidence unavailable; cleanup removes originals afterward.
Collection deletion preserves library sources and removes its derived comparison
records. A collection containing saved notes cannot be deleted until those notes
are removed; export any notes to keep first. This prevents saved text becoming
unreachable after its collection is removed.

New conversations can be restricted to up to 20 selected sources. Their scope is
saved with the conversation. No selection means the whole collection. Search has
its own source selection. Both retrieval branches use the same authorized revisions.

## Verify changes

Run resource-heavy checks sequentially on low-memory systems:

```powershell
.\venv\Scripts\python.exe -m pytest -q --tb=short
.\venv\Scripts\python.exe scripts/verify_workspace.py integration
.\venv\Scripts\python.exe scripts/verify_workspace.py browser
.\venv\Scripts\python.exe scripts/smoke_workspace_ollama.py
.\venv\Scripts\python.exe scripts/smoke_workspace_summary.py --report .cache/summary-check.json
.\venv\Scripts\python.exe scripts/smoke_workspace_summary.py --multi-passage --report .cache/summary-synthesis-check.json
.\venv\Scripts\python.exe scripts/verify_workspace.py live
.\venv\Scripts\python.exe scripts/verify_workspace.py evaluation --report eval/workspace_results.json
```

To review generated answers separately without repeating retrieval ablations:

```powershell
.\venv\Scripts\python.exe scripts/verify_workspace.py evaluation --answers-only --report eval/workspace_answers.json
```

That report includes expected answers, generated text, numbered supporting
passages, statuses, and timings. Outputs are checkpointed after each question;
`complete: false` means an interrupted/unfinished report. Semantic review remains
separate from structural validation.

On a memory-constrained machine, reuse the saved retrieval ranks for a separate
generation-only pass instead of loading both CPU retrieval models alongside
Ollama:

```powershell
.\venv\Scripts\python.exe scripts/evaluate_workspace_answers.py --report eval/workspace_answer_replay.json
```

Run the retrieval benchmark first. This shares the production citation gate but
replays saved passages; the live pipeline command remains the end-to-end check.
Reports are bound to a canonical SHA-256 fingerprint of their corpus. Missing,
incomplete, or mismatched ranks are rejected before model inference.

The 37-question development corpus was used during implementation. A separate
32-question validation corpus uses distinct fictional sources and facts. Run its
retrieval and generation checks sequentially:

```powershell
.\venv\Scripts\python.exe scripts/verify_workspace.py evaluation --dataset eval/workspace_validation_set.json --report eval/workspace_validation_results.json
.\venv\Scripts\python.exe scripts/evaluate_workspace_answers.py --dataset eval/workspace_validation_set.json --retrieval-report eval/workspace_validation_results.json --report eval/workspace_validation_answers.json
```

Both corpora need semantic review. A `quoted_evidence` response is an exact source
excerpt, explicitly labeled because it may answer only part of a question. A
`completed` response is generated prose with validated citation identities and
literal numeric identifiers; its other claims still need passage review.

The verification CLI creates and removes generated local test databases. The
evaluation corpus is explicitly fictional: four paper-like fixtures and two
article-like fixtures, with factual, multi-source, unanswerable, and hostile-source
questions. Retrieval scores do not establish answer correctness or scientific-domain
accuracy. Unanswerable questions require a separate abstention review.

Frontend checks use `npm run build` and Playwright. Stop the API/frontend first,
then run `verify_workspace.py browser`: it starts temporary servers on ports 8001
and 3000, runs all browser tests against an isolated database, and removes it.
It refuses occupied ports or a frontend compiled for another API target. Document,
article, and research tests mock application data; account/collection tests use
the real isolated API and database. Install Playwright Chromium on Linux; on
Windows the helper uses the installed Edge browser if available.
GitHub Actions includes regression, PostgreSQL/pgvector, and frontend jobs. A local
passing run does not mean a remote Actions run has occurred.

## Backup and restore

Use a new private backup directory. It contains account data and private originals.
The helper holds a storage coordination lock and exports a PostgreSQL snapshot,
then records SHA-256 checksums. It refuses missing required originals.

```powershell
.\venv\Scripts\python.exe scripts/backup_workspace.py create .cache/private-backup
.\venv\Scripts\python.exe scripts/backup_workspace.py verify .cache/private-backup
```

Verification restores into a generated `research_restore_*` database, compares table
counts, migration version, and original checksums, then removes that test database.
It does not overwrite the workspace. To retain a separate restored instance:

```powershell
.\venv\Scripts\python.exe scripts/backup_workspace.py restore-new .cache/private-backup --files-root .cache/restored-originals
```

Use the printed new database name in `WORKSPACE_DB_NAME` and the new originals
directory in `WORKSPACE_SOURCE_STORAGE` when starting the separate API/worker.
Run `alembic -c workspace.alembic.ini upgrade head` with that new database selected
before starting current code against an older restored backup.
Never point a restored database at the current workspace's originals directory.
Keep backups outside version control and copy them to separate storage as needed.

## Recovery and resource profiles

- Use **Check workspace services** for the database, recent worker heartbeat,
  writable storage, configured model availability, and account job counts.
- A stopped worker leaves queued work pending. Restart one worker; leases and
  checkpoints prevent stale attempts from publishing twice. Summary steps yield
  between calls so waiting Q&A receives priority.
- Retryable job failures wait 30 seconds before another attempt, allowing local
  dependencies time to recover. Fresh jobs remain eligible during that delay.
- A missing model or failed generation is shown as failure, not a fabricated answer.
  Check Ollama and the model name before retrying. Existing saved findings remain
  attached to the model and revision that produced them.
- Note edits carry a version. A conflicting save returns 409; refresh the research
  list and explicitly discard/reload before replacing another editor's changes.
- The default BM25 cache budget is 32 MB per process; set
  `WORKSPACE_BM25_CACHE_MB=0` to disable retention. Smaller budgets are available
  for low-memory machines. This changes sparse-index caching, not model accuracy.
- Keep one generation worker on low-memory systems. Summary passage calls use a
  smaller context than synthesis calls. See `PERFORMANCE_NOTES.md` for measured
  model experiments and limits. The smaller 1B candidate was not adopted because
  it failed factual checks. The release uses the evaluated Qwen3 4B model;
  machines with enough resources can use the verified
  GPU override; larger models/contexts still require measured evaluation.
- The supplied CPU thread settings disable tokenizer parallelism, use one Rayon
  thread, and limit OpenMP to two threads. Explicit environment values override
  `.env`. Restart the API and worker after changing these values. These settings
  reduce oversubscription; they cannot compensate for exhausted physical RAM.
  Run builds, benchmarks, and model preparation separately from the app on 8 GB
  machines. With more RAM, tune thread counts against the same question set.

Structured request logs contain route templates, status, request ID, and latency.
Worker attempt logs contain job IDs, kinds, attempt outcomes, and elapsed time.
They exclude document bodies, prompts, passwords, and article query strings.
