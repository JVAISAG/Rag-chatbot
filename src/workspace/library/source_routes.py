"""Owner-scoped uploads and extracted source text."""
import uuid
from datetime import date
from typing import Literal
import unicodedata

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from sqlalchemy import case, select
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.errors import ModelUnavailableError
from src.workspace.library.search import search_collection

from src.workspace.auth.dependencies import require_user
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.library.imports import DEFAULT_STORAGE, MAX_UPLOAD, InvalidUpload, ReplacementConflict, replacement_state, stage_replacement, stage_upload
from src.workspace.library.routes import _collection_errors
from src.workspace.library.url_imports import enqueue_refresh, enqueue_url
from src.workspace.library.web_fetch import UnsafeURL
from src.workspace.library.deletion import delete_source
from src.workspace.library.imports import storage_path
from src.workspace.models import Collection, CollectionSource, Job, Source, SourceReplacement, SourceRevision, User

router = APIRouter(prefix="/api/v2", tags=["sources"])


@router.get('/sources/{source_id}/content')
def original_content(request: Request, source_id: uuid.UUID, revision_id: uuid.UUID | None = None, owner: uuid.UUID = Depends(require_user)):
    stream = None
    try:
        with _collection_errors(), request.app.state.database.transaction() as session:
            source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner).with_for_update(read=True))
            if source is None:
                raise HTTPException(404, 'Source not found.')
            revision = session.scalar(select(SourceRevision).where(SourceRevision.source_id == source_id,
                SourceRevision.id == (revision_id or source.active_revision_id)))
            if revision is None or not revision.storage_key:
                raise HTTPException(404, 'Original revision not available.')
            key = revision.storage_key
            try:
                stream = storage_path(getattr(request.app.state, 'source_storage', DEFAULT_STORAGE), key).open('rb')
            except (OSError, ValueError):
                raise HTTPException(404, 'Original file not available.') from None
            suffix = Path(key).suffix.lower()
            disposition = 'inline' if suffix == '.pdf' else 'attachment'
            filename = f'{revision.id}{suffix}'
        def blocks():
            try:
                while content := stream.read(65536):
                    yield content
            finally:
                stream.close()
        return StreamingResponse(blocks(), background=BackgroundTask(stream.close), media_type='application/pdf' if suffix == '.pdf' else 'application/octet-stream',
            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Content-Security-Policy': 'sandbox', 'Content-Disposition': f'{disposition}; filename="{filename}"'})
    except BaseException:
        if stream is not None:
            stream.close()
        raise


@router.delete("/sources/{source_id}", status_code=204, dependencies=[Depends(require_trusted_origin)])
def remove_source(request: Request, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors():
        try:
            delete_source(request.app.state.database, owner, source_id)
        except LookupError:
            raise HTTPException(404, "Source not found.") from None
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


class SourceMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str | None = Field(default=None, max_length=500)
    authors: str | None = Field(default=None, max_length=1000)
    publication_date: str | None = Field(default=None, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=20)
    reading_status: Literal['unread', 'reading', 'read'] = 'unread'
    expected_revision_id: str | None = Field(default=None, max_length=36)

    @field_validator('expected_revision_id')
    @classmethod
    def validate_expected_revision(cls, value):
        return str(uuid.UUID(value)) if value is not None else None

    @field_validator('tags')
    @classmethod
    def normalize_tags(cls, values):
        tags, seen = [], set()
        for value in values:
            value = ' '.join(value.split())
            if not 1 <= len(value) <= 32 or '\x00' in value or ',' in value:
                raise ValueError('Each tag must have 1–32 characters without commas.')
            try:
                value.encode('utf-8')
            except UnicodeError:
                raise ValueError('Tags contain invalid Unicode.') from None
            key = unicodedata.normalize('NFKC', value).casefold()
            if key not in seen:
                seen.add(key)
                tags.append(value)
        return tags

    @field_validator("title", "authors")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Text contains invalid Unicode.") from None
        if "\x00" in value:
            raise ValueError("Text contains an invalid character.")
        return value or None

    @field_validator("publication_date")
    @classmethod
    def validate_publication_date(cls, value):
        if value is None or value == "":
            return None
        try:
            parsed = date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError("Use a valid date in YYYY-MM-DD format.") from None
        return value


@router.get("/sources")
def library_sources(request: Request, response: Response, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        sources = session.scalars(select(Source).where(Source.owner_id == owner).order_by(Source.created_at, Source.id)).all()
        result = [{"id": str(source.id), "filename": source.filename, "title": source.title,
            'tags': source.tags, 'reading_status': source.reading_status} for source in sources]
    response.headers["Cache-Control"] = "no-store"
    return result


def change_membership(request, owner, collection_id, source_id, attach):
    with _collection_errors(), request.app.state.database.transaction() as session:
        # Use the upload lock order so concurrent deduplication and membership changes serialize.
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        collection = session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner))
        source = session.scalar(select(Source.id).where(Source.id == source_id, Source.owner_id == owner))
        if collection is None or source is None:
            raise HTTPException(404, "Collection or source not found.")
        membership = session.get(CollectionSource, (collection_id, source_id))
        if attach and membership is None:
            session.add(CollectionSource(collection_id=collection_id, source_id=source_id))
        elif not attach and membership is not None:
            session.delete(membership)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post("/collections/{collection_id}/sources/{source_id:uuid}", status_code=204, dependencies=[Depends(require_trusted_origin)])
def attach_source(request: Request, collection_id: uuid.UUID, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    return change_membership(request, owner, collection_id, source_id, True)


@router.delete("/collections/{collection_id}/sources/{source_id:uuid}", status_code=204, dependencies=[Depends(require_trusted_origin)])
def detach_source(request: Request, collection_id: uuid.UUID, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    return change_membership(request, owner, collection_id, source_id, False)


@router.patch("/sources/{source_id}", dependencies=[Depends(require_trusted_origin)])
def update_metadata(request: Request, response: Response, source_id: uuid.UUID, details: SourceMetadataUpdate, owner: uuid.UUID = Depends(require_user)):
    fields = details.model_fields_set - {'expected_revision_id'}
    if not fields:
        raise HTTPException(422, "Supply at least one metadata field.")
    with _collection_errors(), request.app.state.database.transaction() as session:
        source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner).with_for_update())
        if source is None:
            raise HTTPException(404, "Source not found.")
        if 'expected_revision_id' in details.model_fields_set and details.expected_revision_id != (str(source.active_revision_id) if source.active_revision_id else None):
            raise HTTPException(409, 'The document revision changed. Reopen its details before saving.')
        for field in fields:
            value = getattr(details, field)
            setattr(source, field, date.fromisoformat(value) if field == "publication_date" and value else value)
        result = {"id": str(source.id), "title": source.title, "authors": source.authors,
                  "publication_date": source.publication_date.isoformat() if source.publication_date else None,
                  'tags': source.tags, 'reading_status': source.reading_status}
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/sources/{source_id}/retry-index", status_code=202, dependencies=[Depends(require_trusted_origin)])
def retry_index(request: Request, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        revision = session.scalar(select(SourceRevision).join(Source, Source.id == SourceRevision.source_id)
            .where(Source.id == source_id, Source.owner_id == owner,
                   (SourceRevision.id == Source.active_revision_id) | Source.active_revision_id.is_(None)))
        if revision is None:
            raise HTTPException(404, "Extracted source not found.")
        job = session.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "index",
            Job.payload["revision_id"].as_string() == str(revision.id)).with_for_update())
        if job is None:
            raise HTTPException(409, "Start the worker to queue this document first.")
        if job.status == "failed":
            job.status = "pending"
            job.attempts = 0
            job.lease_token = None
            job.lease_expires_at = None
        return {"job_id": str(job.id)}


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @field_validator('source_ids')
    @classmethod
    def valid_sources(cls, values):
        if values is None: return None
        try: return sorted(set(str(uuid.UUID(value)) for value in values))
        except ValueError: raise ValueError('Invalid source identifier.') from None


class URLImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=4096)


@router.post("/collections/{collection_id}/sources/import-url", status_code=202, dependencies=[Depends(require_trusted_origin)])
def import_url(request: Request, collection_id: uuid.UUID, details: URLImportRequest, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors():
        try:
            return enqueue_url(request.app.state.database, owner, collection_id, details.url)
        except LookupError:
            raise HTTPException(404, "Collection not found.") from None
        except UnsafeURL as error:
            raise HTTPException(422, str(error)) from None


@router.get("/jobs/{job_id}")
def import_status(request: Request, response: Response, job_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        job = session.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner, Job.kind == "url_import"))
        if job is None:
            raise HTTPException(404, "Import not found.")
        result = {"id": str(job.id), "status": job.status,
                  "source_id": job.payload.get("source_id") if job.status == "completed" else None}
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/sources/{source_id}/refresh", status_code=202, dependencies=[Depends(require_trusted_origin)])
def refresh_source(request: Request, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors():
        try:
            return enqueue_refresh(request.app.state.database, owner, source_id)
        except LookupError:
            raise HTTPException(404, "Source not found.") from None
        except ReplacementConflict as error:
            raise HTTPException(409, str(error)) from None


@router.post("/collections/{collection_id}/search", dependencies=[Depends(require_trusted_origin)])
def search(request: Request, response: Response, collection_id: uuid.UUID, details: SearchRequest, owner: uuid.UUID = Depends(require_user)):
    if not details.query.strip():
        raise HTTPException(422, "Enter a search query.")
    with _collection_errors():
        try:
            results = search_collection(request.app.state.database, owner, collection_id, details.query, **({'source_ids': details.source_ids} if details.source_ids is not None else {}))
        except LookupError:
            raise HTTPException(404, "Collection not found.") from None
        except ModelUnavailableError:
            raise HTTPException(503, "Search models are unavailable. Prepare the local models and retry.") from None
    response.headers["Cache-Control"] = "no-store"
    return results


@router.post("/collections/{collection_id}/sources/upload", status_code=202, dependencies=[Depends(require_trusted_origin)])
async def upload(request: Request, collection_id: uuid.UUID, file: UploadFile = File(...), owner: uuid.UUID = Depends(require_user)):
    try:
        content = await file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "Files must be at most 10 MB.")
        with _collection_errors():
            try:
                return await run_in_threadpool(stage_upload, request.app.state.database,
                    getattr(request.app.state, "source_storage", DEFAULT_STORAGE), owner, collection_id, file.filename or "", content)
            except LookupError:
                raise HTTPException(404, "Collection not found.") from None
            except InvalidUpload as error:
                raise HTTPException(422, str(error)) from None
            except ReplacementConflict as error:
                raise HTTPException(409, str(error)) from None
    finally:
        await file.close()


@router.post("/sources/{source_id}/replace", status_code=202, dependencies=[Depends(require_trusted_origin)])
async def replace(request: Request, source_id: uuid.UUID, file: UploadFile = File(...), owner: uuid.UUID = Depends(require_user)):
    try:
        content = await file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "Files must be at most 10 MB.")
        with _collection_errors():
            try:
                return await run_in_threadpool(stage_replacement, request.app.state.database,
                    getattr(request.app.state, "source_storage", DEFAULT_STORAGE), owner, source_id, file.filename or "", content)
            except LookupError:
                raise HTTPException(404, "Source not found.") from None
            except InvalidUpload as error:
                raise HTTPException(422, str(error)) from None
            except ReplacementConflict as error:
                raise HTTPException(409, str(error)) from None
    finally:
        await file.close()


@router.get("/collections/{collection_id}/sources")
def sources(request: Request, response: Response, collection_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
            raise HTTPException(404, "Collection not found.")
        rows = session.execute(select(Source, Job.status, SourceRevision).join(CollectionSource, CollectionSource.source_id == Source.id)
            .join(Job, Source.job_id == Job.id).outerjoin(SourceRevision, (SourceRevision.source_id == Source.id) &
                ((SourceRevision.id == Source.active_revision_id) | Source.active_revision_id.is_(None)))
            .where(CollectionSource.collection_id == collection_id, Source.owner_id == owner).order_by(Source.created_at, Source.id)).all()
        result = []
        for source, status, revision in rows:
            state = "failed" if status == "completed" else status
            if revision:
                state = "extracted"
                index_status = session.scalar(select(Job.status).where(Job.owner_id == owner, Job.kind == "index",
                    Job.payload["revision_id"].as_string() == str(revision.id)))
                if index_status:
                    state = "indexing_failed" if index_status == "failed" else "indexing"
                if revision.embedding_model:
                    state = "ready"
            replacement = session.scalar(select(SourceReplacement).where(SourceReplacement.source_id == source.id)
                .order_by(case((SourceReplacement.status == "staged", 0), (SourceReplacement.status == "published", 1), else_=2),
                          SourceReplacement.created_at.desc(), SourceReplacement.id.desc()).limit(1))
            refresh = session.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "url_refresh",
                Job.payload["source_id"].as_string() == str(source.id)).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
            result.append({"id": str(source.id), "filename": source.filename, "job_id": str(source.job_id), "status": state,
                           "active_revision_id": str(source.active_revision_id) if source.active_revision_id else None,
                           "replacement_status": replacement_state(session, replacement) if replacement else None,
                           "original_url": source.original_url,
                           "refresh_status": refresh.status if refresh else None,
                           "refresh_outcome": refresh.payload.get("outcome") if refresh and refresh.status == "completed" else None,
                           "title": source.title, "authors": source.authors,
                           "publication_date": source.publication_date.isoformat() if source.publication_date else None,
                           'tags': source.tags, 'reading_status': source.reading_status})
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/sources/{source_id}/text")
def text(request: Request, response: Response, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner))
        if source is None:
            raise HTTPException(404, "Source not found.")
        revision = session.scalar(select(SourceRevision).where(SourceRevision.source_id == source_id,
            (SourceRevision.id == source.active_revision_id) if source.active_revision_id else True))
        if revision is None:
            raise HTTPException(409, "Source text is not available yet.")
        result = {"id": str(source.id), "filename": revision.filename or source.filename, "revision_id": str(revision.id), "pages": revision.pages}
    response.headers["Cache-Control"] = "no-store"
    return result
