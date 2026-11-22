"""Transactional job leasing for PostgreSQL workers."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import and_, case, or_, select, update

from src.workspace.database import WorkspaceDatabase
from src.workspace.models import Job

RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    owner_id: uuid.UUID
    kind: str
    payload: dict
    lease_token: uuid.UUID
    attempts: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_job(database: WorkspaceDatabase, *, kinds: tuple[str, ...], lease: timedelta) -> ClaimedJob | None:
    """Claim one eligible job; expired final attempts are marked failed."""
    if not kinds or lease <= timedelta(0):
        raise ValueError("Job kinds and a positive lease are required.")
    now = _now()
    with database.transaction() as session:
        session.execute(
            update(Job).where(
                Job.kind.in_(kinds), Job.status == "running", Job.lease_expires_at <= now,
                Job.attempts >= Job.max_attempts,
            ).values(status="failed", lease_token=None, lease_expires_at=None, updated_at=now)
        )
        job = session.scalar(
            select(Job).where(
                Job.kind.in_(kinds), Job.attempts < Job.max_attempts,
                or_(and_(Job.status == "pending", or_(Job.attempts == 0, Job.updated_at <= now - RETRY_DELAY)),
                    and_(Job.status == "running", Job.lease_expires_at <= now)),
            ).order_by(case((Job.kind == 'answer', 0), else_=1), Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1)
        )
        if job is None:
            return None
        token = uuid.uuid4()
        job.status = "running"
        job.attempts += 1
        job.lease_token = token
        job.lease_expires_at = now + lease
        job.updated_at = now
        return ClaimedJob(job.id, job.owner_id, job.kind, dict(job.payload), token, job.attempts)


def renew_lease(database: WorkspaceDatabase, job_id: uuid.UUID, token: uuid.UUID, *, lease: timedelta) -> bool:
    if lease <= timedelta(0):
        raise ValueError("A positive lease is required.")
    now = _now()
    with database.transaction() as session:
        result = session.execute(update(Job).where(
            Job.id == job_id, Job.status == "running", Job.lease_token == token, Job.lease_expires_at > now,
        ).values(lease_expires_at=now + lease, updated_at=now))
        return result.rowcount == 1


def finish_job(database: WorkspaceDatabase, job_id: uuid.UUID, token: uuid.UUID, *, success: bool, retryable: bool = False) -> bool:
    """Finish a live lease, or return a retryable failure to the queue."""
    now = _now()
    with database.transaction() as session:
        job = session.scalar(select(Job).where(
            Job.id == job_id, Job.status == "running", Job.lease_token == token, Job.lease_expires_at > now,
        ).with_for_update())
        if job is None:
            return False
        job.status = "completed" if success else ("pending" if retryable and job.attempts < job.max_attempts else "failed")
        job.lease_token = None
        job.lease_expires_at = None
        job.updated_at = now
        return True
