"""Build and atomically publish searchable document chunks."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from src.chunking.text_splitter import process_documents
from src.embeddings.models import generate_embeddings
from src.workspace.jobs.worker import LeaseLost, PermanentJobError
from src.workspace.models import Chunk, Job, Source, SourceReplacement, SourceRevision, User
from src.workspace.vectors import validate_vector

MODEL = "all-MiniLM-L6-v2"


def enqueue_missing_indexes(database):
    """Queue previously extracted revisions when upgrading the workspace."""
    with database.transaction() as session:
        rows = session.execute(select(SourceRevision, Source.owner_id).join(Source, Source.id == SourceRevision.source_id)
            .where(SourceRevision.embedding_model.is_(None)).with_for_update()).all()
        for revision, owner in rows:
            existing = session.scalar(select(Job.id).where(Job.owner_id == owner, Job.kind == "index",
                Job.payload["revision_id"].as_string() == str(revision.id)))
            if existing is None:
                session.add(Job(owner_id=owner, kind="index", payload={"revision_id": str(revision.id)}))
                session.flush()


def indexing_handler(database, *, embed=generate_embeddings, split=process_documents):
    def index(claimed, context):
        revision_id = uuid.UUID(claimed.payload["revision_id"])
        with database.transaction() as session:
            row = session.execute(select(SourceRevision, Source.filename).join(Source, Source.id == SourceRevision.source_id)
                .where(SourceRevision.id == revision_id, Source.owner_id == claimed.owner_id)).one_or_none()
            if row is None:
                raise PermanentJobError("Revision unavailable.")
            revision, filename = row
            filename = revision.filename or filename
            if revision.embedding_model == MODEL:
                return
            documents = [{"text": page["text"], "source": filename, "metadata": {"page": page.get("page")}} for page in revision.pages]
        context.ensure_active()
        chunks = split(documents)
        if not chunks:
            raise PermanentJobError("No searchable text.")
        vectors = embed([chunk["text"] for chunk in chunks])
        if len(vectors) != len(chunks):
            raise PermanentJobError("Embedding count mismatch.")
        try:
            vectors = [validate_vector(vector) for vector in vectors]
        except (ValueError, TypeError):
            raise PermanentJobError("Invalid embedding output.") from None
        context.ensure_active()
        with database.transaction() as session:
            # Match staging's account-first lock order: publication and uploads
            # must not race over an account's content hashes.
            session.scalar(select(User.id).where(User.id == claimed.owner_id).with_for_update())
            job = session.scalar(select(Job).where(Job.id == claimed.id).with_for_update())
            expiry = job.lease_expires_at if job else None
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if job is None or job.status != "running" or job.lease_token != claimed.lease_token or expiry is None or expiry <= datetime.now(timezone.utc):
                raise LeaseLost("Lease expired.")
            revision = session.scalar(select(SourceRevision).join(Source, Source.id == SourceRevision.source_id)
                .where(SourceRevision.id == revision_id, Source.owner_id == claimed.owner_id).with_for_update())
            if revision is None:
                raise PermanentJobError("Revision unavailable.")
            if revision.embedding_model == MODEL:
                return
            replacement = session.scalar(select(SourceReplacement).where(SourceReplacement.revision_id == revision_id).with_for_update())
            if replacement and (replacement.status != "staged" or replacement.index_job_id != claimed.id):
                raise PermanentJobError("Replacement unavailable.")
            for ordinal, (chunk, vector) in enumerate(zip(chunks, vectors)):
                session.add(Chunk(id=uuid.uuid5(revision_id, str(ordinal)), revision_id=revision_id, ordinal=ordinal,
                    page=chunk["metadata"].get("page"), text=chunk["text"], embedding=vector))
            revision.embedding_model = MODEL
            source = session.get(Source, revision.source_id)
            if replacement:
                duplicate = session.scalar(select(Source.id).where(Source.owner_id == claimed.owner_id,
                    Source.content_hash == replacement.content_hash, Source.id != source.id))
                if duplicate is not None:
                    raise PermanentJobError("Replacement conflicts with another document.")
                source.active_revision_id = revision.id
                source.reading_status = 'unread'
                source.filename, source.storage_key, source.content_hash = replacement.filename, replacement.storage_key, replacement.content_hash
                source.original_url = revision.original_url
                replacement.status = "published"
            elif source.active_revision_id is None:
                source.active_revision_id = revision.id
    return index
