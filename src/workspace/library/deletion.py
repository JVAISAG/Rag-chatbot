"""Delete owned sources and durably reclaim their private files."""
from sqlalchemy import or_, select

from src.workspace.jobs.worker import PermanentJobError
from src.workspace.library.cleanup import GENERATED_KEY
from src.workspace.library.imports import lock_storage, storage_path
from src.workspace.library.url_imports import _check_lease
from src.workspace.library.sparse_cache import SPARSE_CACHE
from src.workspace.models import Job, Source, SourceReplacement, SourceRevision, User


def delete_source(database, owner, source_id):
    with database.transaction() as session:
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        source = session.scalar(select(Source).where(Source.id == source_id, Source.owner_id == owner))
        if source is None:
            raise LookupError("Source not found.")
        # Fence extractors before locking the source, matching their job-first order.
        extraction_ids = [source.job_id] + list(session.scalars(select(SourceReplacement.extract_job_id).where(SourceReplacement.source_id == source_id)))
        list(session.scalars(select(Job).where(Job.id.in_(extraction_ids)).order_by(Job.id).with_for_update()))
        source = session.scalar(select(Source).where(Source.id == source_id).with_for_update())
        revisions = list(session.scalars(select(SourceRevision).where(SourceRevision.source_id == source_id)))
        replacements = list(session.scalars(select(SourceReplacement).where(SourceReplacement.source_id == source_id)))
        keys = {source.storage_key} | {row.storage_key for row in revisions} | {row.storage_key for row in replacements}
        revision_ids = [str(row.id) for row in revisions]
        jobs = session.scalars(select(Job).where(Job.owner_id == owner, Job.status.in_(['pending', 'running']), or_(
            Job.id.in_(extraction_ids),
            (Job.kind == 'index') & Job.payload['revision_id'].as_string().in_(revision_ids),
            (Job.kind == 'url_refresh') & (Job.payload['source_id'].as_string() == str(source_id)),
            (Job.kind == 'summary') & (Job.payload['source_id'].as_string() == str(source_id)),
        )).order_by(Job.id).with_for_update()).all()
        for job in jobs:
            job.status, job.lease_token, job.lease_expires_at = 'failed', None, None
        session.add(Job(owner_id=owner, kind='cleanup_source', payload={'keys': sorted(key for key in keys if key)}))
        session.delete(source)
    SPARSE_CACHE.invalidate_owner(owner)


def cleanup_source_handler(database, root):
    def run(claimed, context):
        context.ensure_active()
        with database.transaction() as session:
            # The storage lock precedes all reference reads, as in reconciliation.
            lock_storage(session)
            job = session.scalar(select(Job).where(Job.id == claimed.id).with_for_update())
            _check_lease(job, claimed)
            keys = claimed.payload.get('keys', [])
            if not isinstance(keys, list) or any(not isinstance(key, str) or not GENERATED_KEY.fullmatch(key) for key in keys):
                raise PermanentJobError('Invalid cleanup keys.')
            referenced = set(session.scalars(select(Source.storage_key)))
            referenced.update(session.scalars(select(SourceRevision.storage_key)))
            referenced.update(session.scalars(select(SourceReplacement.storage_key)))
            for key in keys:
                context.ensure_active()
                _check_lease(job, claimed)
                if key not in referenced:
                    storage_path(root, key).unlink(missing_ok=True)
    return run
