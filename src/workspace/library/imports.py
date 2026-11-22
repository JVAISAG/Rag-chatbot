"""Private file staging and idempotent text extraction."""
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import uuid
import os

from sqlalchemy import select, text
from dotenv import dotenv_values
from src.workspace.database import DEFAULT_ENV_FILE

from src.errors import DocumentError
from src.ingestion.document_loader import ALLOWED_EXTENSIONS, load_document
from src.workspace.jobs.worker import LeaseLost, PermanentJobError
from src.workspace.models import Collection, CollectionSource, Job, Source, SourceReplacement, SourceRevision, User


MAX_UPLOAD = 10 * 1024 * 1024
DEFAULT_STORAGE = Path(os.getenv('WORKSPACE_SOURCE_STORAGE') or dotenv_values(DEFAULT_ENV_FILE).get('WORKSPACE_SOURCE_STORAGE') or str(Path(__file__).resolve().parents[3] / 'data' / 'workspace' / 'originals')).resolve()
# A transaction-scoped lock shared by file staging and orphan reconciliation.
STORAGE_LOCK_ID = 0x52414753544F5245


def lock_storage(session):
    """Prevent PostgreSQL cleanup from racing an uncommitted staged file."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": STORAGE_LOCK_ID})


class InvalidUpload(ValueError):
    """A client supplied an unsupported upload."""


class ReplacementConflict(ValueError):
    """A source or replacement conflicts with an in-progress operation."""


def validate_upload(filename, content):
    filename = filename.replace("\\", "/").split("/")[-1]
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS or not filename or len(filename) > 255 or "\x00" in filename:
        raise InvalidUpload("Choose a PDF, DOCX, TXT, or Markdown file with a name up to 255 characters.")
    if not content or len(content) > MAX_UPLOAD:
        raise InvalidUpload("Files must be nonempty and at most 10 MB.")
    return filename, extension, hashlib.sha256(content).hexdigest()


def replacement_state(session, replacement):
    if replacement.status != "staged":
        return replacement.status
    extract = session.get(Job, replacement.extract_job_id)
    index = session.get(Job, replacement.index_job_id) if replacement.index_job_id else None
    if extract is None or extract.status == "failed" or (index and index.status == "failed"):
        return "failed"
    if index:
        return "indexing"
    return "processing"


def active_replacements(session, owner, *, digest=None):
    query = select(SourceReplacement).join(Source, Source.id == SourceReplacement.source_id).where(
        Source.owner_id == owner, SourceReplacement.status == "staged")
    if digest is not None:
        query = query.where(SourceReplacement.content_hash == digest)
    return [item for item in session.scalars(query) if replacement_state(session, item) in {"processing", "indexing"}]


def active_refresh(session, owner, source_id):
    return session.scalar(select(Job).where(Job.owner_id == owner, Job.kind == "url_refresh",
        Job.status.in_(["pending", "running"]), Job.payload["source_id"].as_string() == str(source_id)))


def storage_path(root: Path, key: str) -> Path:
    path = (root / key).resolve()
    if not path.is_relative_to(root.resolve()) or path.parent != root.resolve():
        raise ValueError("Invalid storage key.")
    return path


def stage_upload(database, root: Path, owner: uuid.UUID, collection_id: uuid.UUID, filename: str, content: bytes):
    filename, extension, digest = validate_upload(filename, content)
    written = None
    try:
        with database.transaction() as session:
            # Serialize per account so simultaneous identical imports deduplicate.
            session.scalar(select(User.id).where(User.id == owner).with_for_update())
            if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
                raise LookupError("Collection not found.")
            source = session.scalar(select(Source).where(Source.owner_id == owner, Source.content_hash == digest))
            if source is None:
                if active_replacements(session, owner, digest=digest):
                    raise ReplacementConflict("This file is being processed as a replacement. Try again when it finishes.")
                lock_storage(session)
                source_id, job_id = uuid.uuid4(), uuid.uuid4()
                key = source_id.hex + extension
                root.mkdir(parents=True, exist_ok=True)
                destination = storage_path(root, key)
                with destination.open("xb") as output:
                    written = destination
                    output.write(content)
                session.add(Job(id=job_id, owner_id=owner, kind="extract", payload={"source_id": str(source_id)}))
                session.flush()
                source = Source(id=source_id, owner_id=owner, filename=filename, content_hash=digest, storage_key=key, job_id=job_id)
                session.add(source)
                session.flush()
            if session.get(CollectionSource, (collection_id, source.id)) is None:
                session.add(CollectionSource(collection_id=collection_id, source_id=source.id))
            result = {"id": str(source.id), "filename": source.filename, "job_id": str(source.job_id)}
        return result
    except BaseException:
        if written is not None:
            written.unlink(missing_ok=True)
        raise


def stage_replacement(database, root: Path, owner: uuid.UUID, source_id: uuid.UUID, filename: str, content: bytes):
    filename, extension, digest = validate_upload(filename, content)
    written = None
    try:
        with database.transaction() as session:
            session.scalar(select(User.id).where(User.id == owner).with_for_update())
            source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner).with_for_update())
            if source is None:
                raise LookupError("Source not found.")
            if source.active_revision_id is None:
                raise ReplacementConflict("Wait for the current document to finish indexing before replacing it.")
            if active_refresh(session, owner, source_id):
                raise ReplacementConflict("An article refresh is already processing.")
            if session.scalar(select(Source.id).where(Source.owner_id == owner, Source.content_hash == digest, Source.id != source_id)):
                raise ReplacementConflict("This file already belongs to another document in your library.")
            running = active_replacements(session, owner)
            for item in running:
                if item.source_id == source_id:
                    if item.content_hash == digest:
                        return {"id": str(source_id), "job_id": str(item.extract_job_id), "unchanged": False}
                    raise ReplacementConflict("A replacement for this document is already processing.")
                if item.content_hash == digest:
                    raise ReplacementConflict("This file is being processed for another document.")
            if source.content_hash == digest:
                return {"id": str(source_id), "job_id": None, "unchanged": True}
            for old in session.scalars(select(SourceReplacement).where(SourceReplacement.source_id == source_id, SourceReplacement.status == "staged")):
                old.status = "abandoned"
            lock_storage(session)
            replacement_id, job_id = uuid.uuid4(), uuid.uuid4()
            key = replacement_id.hex + extension
            root.mkdir(parents=True, exist_ok=True)
            destination = storage_path(root, key)
            with destination.open("xb") as output:
                written = destination
                output.write(content)
            session.add(Job(id=job_id, owner_id=owner, kind="extract", payload={"source_id": str(source_id), "replacement_id": str(replacement_id)}))
            session.flush()
            session.add(SourceReplacement(id=replacement_id, source_id=source_id, extract_job_id=job_id,
                filename=filename, storage_key=key, content_hash=digest))
            return {"id": str(source_id), "job_id": str(job_id), "unchanged": False}
    except BaseException:
        if written is not None:
            written.unlink(missing_ok=True)
        raise


def extraction_handler(database, root: Path):
    def extract(claimed, context):
        replacement_id = uuid.UUID(claimed.payload["replacement_id"]) if claimed.payload.get("replacement_id") else None
        with database.transaction() as session:
            source = session.scalar(select(Source).where(Source.id == uuid.UUID(claimed.payload["source_id"]), Source.owner_id == claimed.owner_id))
            if source is None:
                raise PermanentJobError("Source unavailable.")
            source_id = source.id
            if replacement_id:
                replacement = session.get(SourceReplacement, replacement_id)
                if replacement is None or replacement.source_id != source_id or replacement.extract_job_id != claimed.id or replacement.status != "staged":
                    raise PermanentJobError("Replacement unavailable.")
                if replacement.revision_id is not None:
                    return
                key, filename, digest, original_url = replacement.storage_key, replacement.filename, replacement.content_hash, replacement.original_url
            else:
                if source.job_id != claimed.id:
                    raise PermanentJobError("Source unavailable.")
                key, filename, digest, original_url = source.storage_key, source.filename, source.content_hash, source.original_url
                if session.scalar(select(SourceRevision.id).where(SourceRevision.source_id == source_id)) is not None:
                    return
        context.ensure_active()
        article_metadata = None
        try:
            if key.endswith('.html'):
                import trafilatura
                html = storage_path(root, key).read_bytes()
                text = trafilatura.extract(html, include_comments=False, include_tables=True)
                if not text or not text.strip():
                    raise DocumentError("No readable article text.")
                documents = [{"text": text, "metadata": {"page": None}}]
                try:
                    metadata = trafilatura.extract_metadata(html)
                    if metadata:
                        clean = lambda value, limit: (str(value).replace('\x00', '').strip()[:limit] or None) if value else None
                        try:
                            published = date.fromisoformat(metadata.date) if metadata.date else None
                        except (ValueError, TypeError):
                            published = None
                        article_metadata = (clean(metadata.title, 500), clean(metadata.author, 1000), published)
                except Exception:
                    pass  # Article text remains usable if optional metadata is malformed.
            else:
                documents = load_document(str(storage_path(root, key)), source=filename)
            if sum(len(item["text"]) for item in documents) > 2_000_000:
                raise DocumentError("Extracted text exceeds the processing limit.")
            pages = [{"text": item["text"], "page": item["metadata"].get("page")} for item in documents]
        except DocumentError:
            raise PermanentJobError("Document could not be extracted.") from None
        context.ensure_active()
        with database.transaction() as session:
            # Fence publication in the same transaction as the revision write.
            job = session.scalar(select(Job).where(Job.id == claimed.id).with_for_update())
            now = datetime.now(timezone.utc)
            expiry = job.lease_expires_at if job else None
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if job is None or job.status != "running" or job.lease_token != claimed.lease_token or expiry is None or expiry <= now:
                raise LeaseLost("Lease expired.")
            source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == claimed.owner_id).with_for_update())
            if source is None:
                raise PermanentJobError("Source unavailable.")
            replacement = session.get(SourceReplacement, replacement_id) if replacement_id else None
            if replacement_id and (replacement is None or replacement.source_id != source_id or replacement.extract_job_id != claimed.id or replacement.status != "staged"):
                raise PermanentJobError("Replacement unavailable.")
            if (replacement and replacement.revision_id is None) or (not replacement_id and session.scalar(select(SourceRevision.id).where(SourceRevision.source_id == source_id)) is None):
                revision_id = uuid.uuid4()
                index_job_id = uuid.uuid4()
                session.add(SourceRevision(id=revision_id, source_id=source_id, pages=pages, extraction_version="loader-v1", filename=filename, storage_key=key, content_hash=digest, original_url=original_url))
                session.add(Job(id=index_job_id, owner_id=claimed.owner_id, kind="index", payload={"revision_id": str(revision_id)}))
                session.flush()
                if replacement:
                    replacement.revision_id, replacement.index_job_id = revision_id, index_job_id
                elif article_metadata:
                    title, authors, published = article_metadata
                    if source.title is None: source.title = title
                    if source.authors is None: source.authors = authors
                    if source.publication_date is None: source.publication_date = published
    return extract
