# Local research workspace database

The research workspace uses a separate PostgreSQL service for local development.
Its Docker image includes pgvector and is defined in `compose.workspace.yaml`.
This setup does not modify the current application's Chroma database or documents.
For the complete release workflow, diagnostics, isolated verification, and
backup/restore, use [LOCAL_RELEASE.md](LOCAL_RELEASE.md).

## Start the database

1. Start Docker Desktop and wait until its engine is running.
2. Create a local `.env` file from `.env.example` if you do not already have one.
   Do not replace an existing `.env` file.
3. Add `WORKSPACE_DB_PASSWORD` with a local development password to `.env`.
   This file is ignored by Git. Do not commit the password.
4. From the project directory, start the service:

   ```powershell
   docker compose -f compose.workspace.yaml up -d
   ```

5. Check its status:

   ```powershell
   docker compose -f compose.workspace.yaml ps
   ```

The service defaults to `127.0.0.1:5433`, with the database and user both named
`research_workspace`. Override these in `.env` with `WORKSPACE_DB_PORT`,
`WORKSPACE_DB_NAME`, and `WORKSPACE_DB_USER` if needed. The database port is
bound to the local machine only.

PostgreSQL data persists in the `workspace_postgres_data` Docker volume. The
following command stops the service while preserving that volume:

```powershell
docker compose -f compose.workspace.yaml down
```

The image includes the pgvector extension files. To apply workspace migrations
after starting the database and installing requirements, run:

```powershell
.\venv\Scripts\python.exe -m alembic -c workspace.alembic.ini upgrade head
```

Migrations read the workspace database settings described below. The first
migrations enable pgvector and create the account, login identifier, session,
login-attempt counter, and collection tables.

Downgrading the account migration deletes its tables and their data. The
pgvector migration intentionally leaves the extension installed during a
downgrade because it might have existed before the workspace migration.

## Run Ollama in Docker

Ollama can run in the same Compose project. The optional `inference` profile
keeps database-only startup and isolated database tests independent of the model.
Start Docker Desktop, then run these commands from the project root:

```powershell
docker compose -f compose.workspace.yaml up -d ollama
docker compose -f compose.workspace.yaml exec -T ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
docker compose -f compose.workspace.yaml exec -T ollama ollama list
```

Before the first pull, check free space on the drive that hosts Docker's disk
image. The downloaded image, its unpacked layers, and the model all need space.
Keeping this repository on D: does not move Docker's storage off C:. On Windows,
check **Docker Desktop > Settings > Resources > Advanced > Disk image location**.
If needed, use that setting to move the disk to a larger drive; Docker restarts
and temporarily stops other containers during the move. Keep existing Docker
data rather than resetting or deleting its disk.

The service uses the official `ollama/ollama` image and CPU inference. Its API
is bound to `127.0.0.1:11434`; the host API and worker keep using
`OLLAMA_HOST=http://127.0.0.1:11434` and `OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M`.
The health check confirms the server responds; `ollama list` must also show the
configured model after the initial download. First startup downloads the image
and model, so allow time and disk space for both.
If an image download is interrupted with `unexpected EOF`, rerun the startup
command. Completed image layers remain cached. Start the model download and live
check only after the container is running successfully.

Models persist in the `workspace_ollama_data` named volume. To stop inference
without removing the model or database, run:

```powershell
docker compose -f compose.workspace.yaml stop ollama
```

After installing Python requirements and preparing the tokenizer, verify real
generation with this opt-in check:

```powershell
.\venv\Scripts\python.exe scripts/smoke_workspace_ollama.py
```

It runs the actual answer worker against a temporary SQLite database and fixed
synthetic evidence, checks a cited answer and its saved evidence, then removes
the temporary database. It does not test retrieval quality or touch your
workspace library. PostgreSQL retrieval and isolation have separate tests.

For the database integration checks, install `requirements-dev.txt` and run:

```powershell
.\venv\Scripts\python.exe scripts/verify_workspace.py integration
```

To check the full API and worker pipeline with real embeddings, reranking, and
Ollama, prepare the retrieval models and run:

```powershell
.\venv\Scripts\python.exe scripts/prepare_models.py --embeddings --reranker
.\venv\Scripts\python.exe scripts/verify_workspace.py live
```

Both commands create a generated temporary database on the configured local
PostgreSQL server and remove it afterward. The database role needs permission to
create databases. The live check uses synthetic text in temporary file storage,
checks answers and a follow-up, empty-collection handling, and account isolation.
It requires local Ollama and cached retrieval models; it does not add accounts or
documents to the workspace library. This is a functional check, not an answer
quality or performance benchmark.

## Check the workspace API connection

Install the project's Python requirements. For local HTTP, add
`WORKSPACE_COOKIE_SECURE=false` to the project's `.env` file. Without this
explicit setting, session cookies default to `Secure` and will not work over
ordinary HTTP. The example `.env.example` includes the local setting.

Start the workspace API in a separate terminal:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn src.workspace.main:app --host 127.0.0.1 --port 8001 --no-proxy-headers
```

The workspace reads the same `WORKSPACE_DB_PASSWORD`, `WORKSPACE_DB_PORT`,
`WORKSPACE_DB_NAME`, and `WORKSPACE_DB_USER` values from the project `.env` file
or environment variables. Environment variables take precedence. The optional
`WORKSPACE_DB_HOST` defaults to `127.0.0.1`. Restart the API after changing
database settings because its connection pool keeps the settings it first used.

Open `http://127.0.0.1:8001/api/v2/ready` to check whether the database can be
reached. The check returns `503` when configuration is missing or PostgreSQL is
unavailable. It currently checks the connection only; it does not verify tables,
pgvector activation, or Ollama. `/api/v2/health` checks the API process without
opening a database connection.

## Account and session API

After applying migrations and starting the API, send a JSON request to
`POST /api/v2/auth/register` with a `password` and at least one of `username`
or `email`. Passwords must contain 8–128 characters. Usernames must contain
3–32 ASCII letters, numbers, dots, underscores, or hyphens. Usernames and
emails are matched without regard to case. Email syntax is checked without DNS
lookups or sending a verification message. Registration requires a trusted
`Origin` header or a trusted `Referer` header, as do login and logout. The
allowed browser origins are exactly `http://localhost:3000` and
`http://127.0.0.1:3000`. API clients without a browser must supply one of these
origins when sending those requests.

The endpoint returns `201` and the new account ID, `409` when an identifier
is unavailable, `422` for invalid input, and `503` if the database is
unavailable. For a request with one identifier, `409` reveals that identifier's
availability; review that behavior before public deployment. Registration does
not sign the user in.

Send the account's `identifier` (email or username) and `password` to
`POST /api/v2/auth/login`. On success, the response contains the account ID and
an HttpOnly, SameSite=Lax session cookie. The server stores only a hash of its
token. `GET /api/v2/auth/me` returns the signed-in account ID;
`POST /api/v2/auth/logout` revokes and clears the current session. Sessions
expire seven days after sign-in, and signing in again does not revoke other
sessions. Invalid credentials return `401`, and a blocked login returns `429`
with a `Retry-After` header.

The login limit is five failed attempts per account and 30 total attempts per
client within 15 minutes; a block lasts 15 minutes. Both identifiers belonging to
an account share the failure limit. Successful and malformed login submissions
also count toward the client limit. The API counts the connecting peer and does
not use `X-Forwarded-For`. Use the startup command above so Uvicorn does not
replace that peer with an untrusted forwarding header. When a local frontend
proxy forwards requests, its browsers share the proxy's client limit.

To try the account API directly from PowerShell, replace the example credentials
consistently in these commands:

```powershell
$workspaceApi = 'http://127.0.0.1:8001/api/v2/auth'
$workspaceHeaders = @{ Origin = 'http://127.0.0.1:3000' }
$workspaceRegister = @{ username = 'researcher'; password = 'replace-this-password' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$workspaceApi/register" -Headers $workspaceHeaders -ContentType 'application/json' -Body $workspaceRegister

$workspaceLogin = @{ identifier = 'researcher'; password = 'replace-this-password' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$workspaceApi/login" -Headers $workspaceHeaders -ContentType 'application/json' -Body $workspaceLogin -SessionVariable workspaceAuthSession
Invoke-RestMethod -Method Get -Uri "$workspaceApi/me" -WebSession $workspaceAuthSession
Invoke-RestMethod -Method Post -Uri "$workspaceApi/logout" -Headers $workspaceHeaders -WebSession $workspaceAuthSession
```

## Use collections in the frontend

With the database and workspace API running, open another terminal and start the
Next.js frontend:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:3000` or `http://localhost:3000`. Create an account,
sign in, then create, edit, or delete collections. The frontend sends
`/api/v2` requests through its own origin to the workspace API, which defaults
to `http://127.0.0.1:8001`. To use a different API address, set
`WORKSPACE_API_URL` in the frontend terminal before running `npm run dev` (or
before building, when using the production frontend).
If another application is using port 3000, stop it before starting the frontend.

Collection names are unique within each account without regard to letter case;
the same name can be used by different accounts. Names can contain up to 100
characters, and descriptions are optional with a 2,000-character limit. The
server takes the owner from the session and returns `404` for a collection
belonging to another account.

After applying the latest migrations, run the extraction worker in a separate
terminal from the project root:

```powershell
.\venv\Scripts\python.exe -m src.workspace.jobs
```

Open a collection's **Open documents** button to upload one PDF, DOCX, TXT, or
Markdown file per request (10 MB maximum). The worker extracts text in the
background. The interface polls while work is pending and provides **Read text**
after extraction. Originals are stored privately in `data/workspace/originals`,
under generated names. Duplicate content within an account shares the original
and can be attached to another collection. Collections owned by different users
have separate source records. After extraction the worker queues chunking and
embeddings; a source becomes `ready` only when its complete index is published.
Use **Edit details** to optionally set a title, authors, and publication date.
Details belong to the source and appear in every collection containing it; the
original filename remains available when no title is provided. Apply the latest
database migrations before using this feature. Editing these details does not
change passage search, which currently searches the extracted document text.
Use **Remove from collection** to detach a source while retaining it in your
private library. **Add from library** attaches it again without uploading another
copy. A saved answer's reference is marked unavailable while the source is not
in that answer's collection.
Use **Import an article URL** for public HTTP or HTTPS HTML articles and PDFs.
The worker follows up to three redirects after validating every destination,
stores the original privately, extracts readable article text, and indexes it in
the background. The source card links to the final original URL. The fetcher
does not use ambient HTTP proxies and accepts identity-encoded responses up to
10 MB; sites requiring login, blocked private destinations, compressed-only
responses, and pages without extractable text cannot be imported.
Use **Refresh article** on a ready URL source to re-fetch it. Unchanged pages
keep the existing revision; changed pages are indexed before they replace it.
If fetching or indexing fails, the current revision remains available. A refresh
matching another source in the account is rejected without changing either one.
Search uses BM25 and exact pgvector cosine search over the same authorised
revision set, combines results with RRF, and reranks the candidates. The document
worker and API retain BM25 indexes in a process-local LRU cache with a default
32 MB accounted-object budget. Set `WORKSPACE_BM25_CACHE_MB=0` to disable it or
choose another budget before starting each service. Revision changes use new
cache keys, and every search still checks collection ownership and membership.
This avoids repeated BM25 construction; generation latency still needs measurement.
The document
panel shows matching passages with source and page references. Prepare the local
models and tokenizer with `python scripts/prepare_models.py --embeddings --reranker`
before running the worker. Previously extracted documents are queued when the
worker starts. Failed indexing is reported separately from successful extraction;
after correcting a model/setup problem, use **Retry indexing** on the document.
The document panel also supports **Ask documents** and saved conversations. An
answer job uses the collection's authorised indexed passages, saves the evidence
provided to Ollama, and validates citation numbers before publishing. Invalid
citations get one repair attempt, then an unsupported-answer message. Open the
numbered references to inspect their passages. A failed generation is shown as a
failure, not an answer. Ensure Ollama and the configured `OLLAMA_MODEL` are
available; the worker reads the project `.env` file, with environment variables
taking precedence. Citation-number validation cannot establish factual accuracy.
The `qa-v2` prompt lists the allowed markers explicitly; the worker records the
prompt version before generation and keeps the same evidence for a retry.
The worker checks private file storage at startup and approximately hourly while
running. It removes abandoned replacement files and generated files without
database references after a 24-hour grace period. Active uploads, current files,
and published historical revisions are retained. A file that cannot be removed
is retried during a later pass. The database must be available for cleanup.

Deleting a document from the library removes it from every collection, revokes
its extraction/index/refresh jobs, and queues its private files for cleanup.
Saved answers remain, with deleted evidence marked unavailable. Removing a
document from one collection is a separate operation and retains its library record.

Use **Document to summarize** and **Summarize document** to analyze every extracted
passage of a ready source. Each model call saves a checkpoint and queues the next
step; waiting Q&A jobs have priority. Saved summaries retain their revision IDs,
structured findings, and numbered passages. Model failures resume from the last
checkpoint while retries remain. Invalid structured output fails without publishing
a result. Source refresh does not rewrite an older summary; source deletion makes
its summary and evidence unavailable. This covers extracted text, not unreadable
scans, omitted figures, or mathematical interpretation.

Run the opt-in real-model check with synthetic temporary data:

```powershell
.\venv\Scripts\python.exe scripts/smoke_workspace_summary.py
```

To test a different installed model without changing the workspace configuration:

```powershell
.\venv\Scripts\python.exe scripts/smoke_workspace_summary.py --model llama3.2:1b-instruct-q4_K_M --report .cache/summary-small-model.json
```

The report contains only the synthetic study, its generated summary, and elapsed
worker time. Review the findings and references as well as the completion status.

Saved comparisons, versioned notes, and Markdown export are available under
**Research comparisons and notes**. A stopped worker leaves new questions and
uploads pending. See the release runbook for the complete demonstration.

The frontend's browser checks use Playwright. Build the frontend, stop the normal
API/frontend, and run `python scripts/verify_workspace.py browser`. The helper
starts temporary servers and a disposable database, runs every browser scenario,
and removes the database. It supports an existing browser executable through
`PLAYWRIGHT_BROWSER_EXECUTABLE` and selects installed Edge on Windows by default.
