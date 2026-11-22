"""Local, single-process API. Models are initialized only when needed."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Annotated, Any, Literal
import uuid

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.errors import DocumentError, ModelUnavailableError, WebSearchUnavailableError
from src.generation.client import DEFAULT_MODEL, setting
from src.ingestion.document_loader import ALLOWED_EXTENSIONS

load_dotenv()
logger = logging.getLogger(__name__)
MAX_UPLOAD_MB = 10
MAX_UPLOAD_FILES = 10
MAX_BATCH_MB = 25


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] | None = Field(default=None, max_length=20)
    use_hybrid: bool = False
    use_reranking: bool = False

    @field_validator("history")
    @classmethod
    def bound_history(cls, value):
        if value and sum(len(message.content) for message in value) > 20000:
            raise ValueError("Conversation history exceeds 20000 characters.")
        return value


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


def default_pipeline_factory():
    from src.pipeline import RAGPipeline

    return RAGPipeline(
        data_dir=os.getenv("DATA_DIR", "./data"), db_path=os.getenv("CHROMA_PATH", "./chroma_db"),
        llm_model=setting("OLLAMA_MODEL", DEFAULT_MODEL),
    )


def get_pipeline(request: Request):
    with request.app.state.pipeline_lock:
        if request.app.state.pipeline is None:
            request.app.state.pipeline = request.app.state.pipeline_factory()
        return request.app.state.pipeline


Pipeline = Annotated[Any, Depends(get_pipeline)]


def validate_uploads(files):
    if not files or len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"Upload between 1 and {MAX_UPLOAD_FILES} files at a time.")
    total, names = 0, set()
    for file in files:
        name = file.filename or ""
        if not name.strip() or len(name) > 255 or name in {".", ".."} or any(char in name for char in '/\\\x00\r\n'):
            raise HTTPException(400, "Use a plain filename without directories or control characters.")
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise HTTPException(400, "Filenames cannot contain control characters.")
        if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, "Supported document types: PDF, DOCX, TXT, MD.")
        if name in names:
            raise HTTPException(400, "Each file in an upload must have a different filename.")
        names.add(name)
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
        if size == 0 or size > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(400, f"Each file must contain data and be at most {MAX_UPLOAD_MB} MB.")
        total += size
    if total > MAX_BATCH_MB * 1024 * 1024:
        raise HTTPException(400, f"The total upload must be at most {MAX_BATCH_MB} MB.")


def create_app(pipeline_factory=None):
    @asynccontextmanager
    async def lifespan(application):
        try:
            yield
        finally:
            if application.state.pipeline is not None:
                application.state.pipeline.close()
                application.state.pipeline = None
            logger.info("Shutting down API server; persistent documents and indexes are retained.")

    application = FastAPI(title="Personal RAG API", version="1.1.0", lifespan=lifespan)
    application.state.pipeline = None
    application.state.pipeline_factory = pipeline_factory or default_pipeline_factory
    application.state.pipeline_lock = Lock()

    @application.exception_handler(ModelUnavailableError)
    async def model_error(request: Request, exc: ModelUnavailableError):
        logger.warning("Local model unavailable at %s.", request.url.path)
        return JSONResponse(status_code=503, content={"detail": "The local model is unavailable. Check Ollama and the configured models."})

    @application.exception_handler(WebSearchUnavailableError)
    async def search_error(request: Request, exc: WebSearchUnavailableError):
        return JSONResponse(status_code=503, content={"detail": "Web search could not return usable results. Try again or ask about uploaded documents."})

    @application.exception_handler(DocumentError)
    async def document_error(request: Request, exc: DocumentError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error at %s.", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "The chatbot could not process your request. Please try again later."})

    @application.get("/api/v1/health")
    def health():
        return {"status": "ok", "pipeline_initialized": application.state.pipeline is not None}

    @application.get("/api/v1/ready")
    def ready(pipeline: Pipeline):
        storage_ready = pipeline.store.collection.count() >= 0
        try:
            response = httpx.get(f"{os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')}/api/tags", timeout=3)
            response.raise_for_status()
            models = [model.get("name", "") for model in response.json().get("models", [])]
            configured = setting("OLLAMA_MODEL", DEFAULT_MODEL)
            model_ready = configured in models or f"{configured}:latest" in models
        except (httpx.HTTPError, ValueError, TypeError):
            model_ready = False
        status = {"storage": storage_ready, "ollama_model": model_ready,
                  "embedding_model_loaded": pipeline._embedding_model is not None}
        return JSONResponse(status_code=200 if storage_ready and model_ready else 503, content=status)

    @application.post("/api/v1/query", response_model=QueryResponse)
    def query_endpoint(req: QueryRequest, pipeline: Pipeline):
        answer, sources = pipeline.query(
            user_query=req.query, history=[message.model_dump() for message in req.history] if req.history else None,
            use_hybrid=req.use_hybrid, use_reranking=req.use_reranking,
        )
        return QueryResponse(answer=answer, sources=sources)

    @application.get("/api/v1/files")
    def list_files(pipeline: Pipeline):
        return {"files": pipeline.list_files()}

    @application.post("/api/v1/upload")
    def upload_files(pipeline: Pipeline, files: list[UploadFile] = File(...)):
        # Synchronous endpoint: parsing and embedding run in a worker thread.
        validate_uploads(files)
        root = Path(pipeline.data_dir)
        root.mkdir(parents=True, exist_ok=True)
        saved, errors = [], []
        for file in files:
            path = root / f"{uuid.uuid4().hex}{Path(file.filename).suffix.lower()}"
            try:
                with path.open("wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                if not pipeline.ingest_file(str(path), file.filename):
                    raise DocumentError("No readable text could be indexed.")
                saved.append(file.filename)
            except DocumentError as exc:
                path.unlink(missing_ok=True)
                errors.append({"file": file.filename, "detail": str(exc)})
            except Exception:
                path.unlink(missing_ok=True)
                raise
        result = {"message": f"Uploaded and indexed {len(saved)} files.", "files": saved, "errors": errors}
        if errors:
            return JSONResponse(status_code=207 if saved else 400, content=result)
        return result

    @application.post("/api/v1/index")
    def rebuild_index(pipeline: Pipeline):
        if not pipeline.build_index():
            raise HTTPException(400, "Failed to rebuild the index.")
        return {"message": "Index rebuilt successfully."}

    @application.delete("/api/v1/file/{filename:path}")
    def delete_file(filename: str, pipeline: Pipeline):
        if not pipeline.remove_file(filename):
            raise HTTPException(404, "Document not found.")
        return {"message": "Document and its indexed chunks were removed."}

    return application


app = create_app()
