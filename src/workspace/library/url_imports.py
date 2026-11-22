"""Owner-scoped queued article imports with fenced publication."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid

from sqlalchemy import select

from src.workspace.jobs.worker import LeaseLost, PermanentJobError
from src.workspace.library.imports import ReplacementConflict, active_refresh, active_replacements, lock_storage, storage_path
from src.workspace.library.web_fetch import UnsafeURL, fetch_public_url, validate_url
from src.workspace.models import Collection, CollectionSource, Job, Source, SourceReplacement, User


def enqueue_url(database, owner, collection_id, url):
    canonical, _, _ = validate_url(url)
    with database.transaction() as session:
        if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
            raise LookupError("Collection not found.")
        job = Job(id=uuid.uuid4(), owner_id=owner, kind="url_import",
                  payload={"url": canonical, "collection_id": str(collection_id)})
        session.add(job)
        return {"job_id": str(job.id)}


def enqueue_refresh(database, owner, source_id):
    with database.transaction() as session:
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner).with_for_update())
        if source is None:
            raise LookupError("Source not found.")
        if not source.original_url or source.active_revision_id is None:
            raise ReplacementConflict("Only indexed URL sources can be refreshed.")
        existing = active_refresh(session, owner, source_id)
        if existing:
            return {"job_id": str(existing.id)}
        if any(item.source_id == source_id for item in active_replacements(session, owner)):
            raise ReplacementConflict("A replacement for this document is already processing.")
        job = Job(id=uuid.uuid4(), owner_id=owner, kind="url_refresh", created_at=datetime.now(timezone.utc),
            payload={"url": source.original_url, "source_id": str(source.id)})
        session.add(job)
        return {"job_id": str(job.id)}


def _check_lease(job, claimed):
    expiry = job.lease_expires_at if job else None
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if job is None or job.owner_id != claimed.owner_id or job.status != 'running' or job.lease_token != claimed.lease_token or expiry is None or expiry <= datetime.now(timezone.utc):
        raise LeaseLost("The import lease expired.")


def url_import_handler(database, root: Path, *, fetch=fetch_public_url):
    def run(claimed, context):
        if claimed.payload.get('source_id'):
            return
        try:
            page = fetch(claimed.payload['url'])
        except UnsafeURL:
            raise PermanentJobError("URL is not public.") from None
        context.ensure_active()
        digest = hashlib.sha256(page.content).hexdigest()
        collection_id = uuid.UUID(claimed.payload['collection_id'])
        extension = '.pdf' if page.content_type == 'application/pdf' else '.html'
        _, host, _ = validate_url(page.url)
        filename = host[:245] + extension
        written = None
        try:
            with database.transaction() as session:
                session.scalar(select(User.id).where(User.id == claimed.owner_id).with_for_update())
                job = session.scalar(select(Job).where(Job.id == claimed.id, Job.kind == 'url_import').with_for_update())
                _check_lease(job, claimed)
                if job.payload.get('source_id'):
                    return
                if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == claimed.owner_id)) is None:
                    raise PermanentJobError("Collection unavailable.")
                source = session.scalar(select(Source).where(Source.owner_id == claimed.owner_id, Source.content_hash == digest))
                if source is None:
                    if active_replacements(session, claimed.owner_id, digest=digest):
                        raise RuntimeError("A matching replacement is processing.")
                    lock_storage(session)
                    source_id, extract_id = uuid.uuid4(), uuid.uuid4()
                    key = source_id.hex + extension
                    root.mkdir(parents=True, exist_ok=True)
                    destination = storage_path(root, key)
                    with destination.open('xb') as output:
                        written = destination
                        output.write(page.content)
                    session.add(Job(id=extract_id, owner_id=claimed.owner_id, kind='extract', payload={'source_id': str(source_id)}))
                    session.flush()
                    source = Source(id=source_id, owner_id=claimed.owner_id, filename=filename,
                        original_url=page.url, content_hash=digest, storage_key=key, job_id=extract_id)
                    session.add(source)
                    session.flush()
                if session.get(CollectionSource, (collection_id, source.id)) is None:
                    session.add(CollectionSource(collection_id=collection_id, source_id=source.id))
                context.ensure_active()
                _check_lease(job, claimed)
                job.payload = {**job.payload, 'source_id': str(source.id)}
        except BaseException:
            if written is not None:
                written.unlink(missing_ok=True)
            raise
    return run


def url_refresh_handler(database, root: Path, *, fetch=fetch_public_url):
    def run(claimed, context):
        if claimed.payload.get('outcome'):
            return
        try:
            page = fetch(claimed.payload['url'])
        except UnsafeURL:
            raise PermanentJobError("URL is not public.") from None
        context.ensure_active()
        digest = hashlib.sha256(page.content).hexdigest()
        source_id = uuid.UUID(claimed.payload['source_id'])
        extension = '.pdf' if page.content_type == 'application/pdf' else '.html'
        _, host, _ = validate_url(page.url)
        filename = host[:245] + extension
        written = None
        try:
            with database.transaction() as session:
                session.scalar(select(User.id).where(User.id == claimed.owner_id).with_for_update())
                job = session.scalar(select(Job).where(Job.id == claimed.id, Job.kind == 'url_refresh').with_for_update())
                _check_lease(job, claimed)
                if job.payload.get('outcome'):
                    return
                source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == claimed.owner_id).with_for_update())
                if source is None or source.original_url != claimed.payload['url'] or source.active_revision_id is None:
                    raise PermanentJobError("Source unavailable.")
                duplicate = session.scalar(select(Source.id).where(Source.owner_id == claimed.owner_id,
                    Source.id != source_id, Source.content_hash == digest))
                competing = active_replacements(session, claimed.owner_id, digest=digest)
                if duplicate or any(item.source_id != source_id for item in competing):
                    job.payload = {**job.payload, 'outcome': 'duplicate'}
                elif source.content_hash == digest:
                    job.payload = {**job.payload, 'outcome': 'unchanged'}
                elif any(item.source_id == source_id for item in active_replacements(session, claimed.owner_id)):
                    job.payload = {**job.payload, 'outcome': 'conflict'}
                else:
                    for old in session.scalars(select(SourceReplacement).where(SourceReplacement.source_id == source_id, SourceReplacement.status == 'staged')):
                        old.status = 'abandoned'
                    lock_storage(session)
                    replacement_id, extract_id = uuid.uuid4(), uuid.uuid4()
                    key = replacement_id.hex + extension
                    root.mkdir(parents=True, exist_ok=True)
                    destination = storage_path(root, key)
                    with destination.open('xb') as output:
                        written = destination
                        output.write(page.content)
                    session.add(Job(id=extract_id, owner_id=claimed.owner_id, kind='extract',
                        payload={'source_id': str(source_id), 'replacement_id': str(replacement_id)}))
                    session.flush()
                    session.add(SourceReplacement(id=replacement_id, source_id=source_id, extract_job_id=extract_id,
                        filename=filename, storage_key=key, content_hash=digest, original_url=page.url))
                    job.payload = {**job.payload, 'outcome': 'staged', 'replacement_id': str(replacement_id)}
                context.ensure_active()
                _check_lease(job, claimed)
        except BaseException:
            if written is not None:
                written.unlink(missing_ok=True)
            raise
    return run
