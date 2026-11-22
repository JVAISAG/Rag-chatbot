# Research workspace and local RAG assistant

A private research workspace for papers, blogs, and articles, built with Next.js,
FastAPI, PostgreSQL/pgvector, and local Ollama inference. Search combines BM25,
dense retrieval, reciprocal rank fusion, and a cross-encoder reranker.

## Start the research workspace

Follow the [local release runbook](docs/LOCAL_RELEASE.md) for database/model
preparation, migrations, CPU or NVIDIA Docker inference, and service startup.
Open **http://127.0.0.1:3000/** after starting the workspace.

The workspace includes accounts, collections, versioned file and public-URL
imports, background jobs, a reader with original files, source-scoped cited
conversations, checkpointed summaries, evidence comparisons, notes, and Markdown
export. Saved evidence is pinned to revisions and becomes unavailable after
source deletion. Note versions prevent conflicting edits from overwriting each
other. The runbook also covers service diagnostics and verified backup/restore.
The reader and questions share a responsive workspace. Answers expose recorded
processing times; exact-excerpt fallbacks are labeled, and numeric dataset/model
identifiers are checked against their cited passages.
Sources also retain private tags and reading progress across collections; changed
revisions become unread after successful publication.

See the [plan and release scope](docs/RESEARCH_WORKSPACE_PLAN.md),
[verification record](docs/WORKSPACE_VERIFICATION.md), and
[performance measurements](docs/PERFORMANCE_NOTES.md). Generated claims need
review against their passages; local synthetic tests do not establish scientific
accuracy or production readiness.

## Original single-user assistant

The original Streamlit/FastAPI application with Chroma persistence is retained
separately and does not share the v2 workspace library. The instructions below
describe that original application. It supports PDF, DOCX, TXT, and Markdown.

## Setup (Python 3.12)

From the project directory on Windows:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/prepare_models.py --embeddings --reranker
```

On macOS/Linux, activate with `source venv/bin/activate` and copy configuration
with `cp .env.example .env`. Dependency versions are pinned to the audited
environment; transitive dependencies are not a complete lockfile.

Install Ollama and prepare the configured generation model:

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Alternatively, run the official Ollama Docker image using the optional service
in [`docs/WORKSPACE_DATABASE.md`](docs/WORKSPACE_DATABASE.md#run-ollama-in-docker).
Both options use the same local API address and configured Qwen3 4B model.

The tokenizer vocabulary and retrieval models need internet access on first
preparation. Their default cache is `.cache/` inside this project. After setup,
document search and generation can run locally. Web-search queries contact
DuckDuckGo and send the rewritten search query to that service. Chroma product
telemetry is disabled. Model memory requirements depend on the machine; this
repository does not promise an 8 GB memory limit.

## Run

Keep Ollama running. Start the API, using one worker:

```powershell
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In another activated terminal:

```powershell
streamlit run app.py
```

Open `http://localhost:8501`. API documentation is at
`http://127.0.0.1:8000/docs`.

Configuration keys are in `.env.example`. The Streamlit frontend uses `BACKEND_URL`;
the backend uses `DATA_DIR`, `CHROMA_PATH`, and the `OLLAMA_*` options.

## Document behavior

- Uploads index only the uploaded file; other documents are not re-embedded.
- The original filename appears in citations. The saved upload uses a generated
  filename, and its mapping is retained in indexed metadata.
- Uploading the same filename and content is a no-op. Changed content under the
  same filename replaces that document, including obsolete chunks and saved files.
  Two different documents that share a filename must be renamed before uploading.
- Removing an item from the upload picker does not delete a saved document.
  Use its explicit Delete button in the saved document list.
- Deletion removes saved files and both retrieval representations, including when
  deleting the last document. A later rebuild does not restore a deleted upload.
- Rebuild reconciles the entire index with supported files currently in `DATA_DIR`.
  An empty data directory produces an empty index. A malformed document aborts
  the rebuild before replacing the previous index.
- PDF page metadata is preserved. Scanned PDFs require OCR before ingestion.
- Uploads allow 10 files per request, 10 MB per file, and 25 MB total.
  Partially successful parsing batches return per-file successes and errors.

Before upgrading a real existing collection, back up `data/` and `chroma_db/`.
Rebuild once to apply the corrected chunking and remove historical duplicate or
stale records. Filenames already lost by an older index cannot always be recovered;
the UUID filename is retained when no original-name mapping survives.

## Health and errors

- `GET /api/v1/health`: liveness, without initializing models or the database.
- `GET /api/v1/ready`: checks storage and Ollama's configured model, and reports
  whether the embedding model has been loaded. This does not test answer quality.
- `GET /api/v1/files`: lists indexed document names and chunk counts.
- Invalid query/history bodies return 422. Invalid documents return 400.
  Missing documents return 404. Model failures return 503; unexpected failures
  return a generic 500 response and are logged on the server.

## Tests and evaluation

```powershell
python -m pip install -r requirements-dev.txt
python scripts/prepare_models.py
python -m pytest -q
python -m pip check
```

Tests substitute model outputs, use real Chroma databases in temporary directories,
and exercise the API and Streamlit interface. They do not require a running Ollama
server. See `docs/AUDIT.md` for the scope and remaining limitations. GitHub Actions
contains the same regression checks; its remote execution has to run after a push.

The retrieval smoke benchmark uses included public synthetic fixtures and a
temporary database, never the application's persistent index:

```powershell
python eval/run.py --reranker
```

Use `--data-dir` and `--eval-set` to supply a separate labelled benchmark. The older
`eval/eval_set.json` is a legacy dataset that requires its own source documents;
it is not the default benchmark. `eval/evaluate.py` forwards to the same runner.

## Scope

The original Streamlit application is local, single-user, and single-worker. It does not implement
authentication, user isolation, rate limiting, distributed indexing, or guaranteed
cross-filesystem/database crash transactions. Do not expose it publicly as a
multi-user service without adding those capabilities. See `docs/ARCHITECTURE.md`.
