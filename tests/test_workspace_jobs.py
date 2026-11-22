"""Job leases reject stale workers and respect retry limits."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import create_engine, event

from src.workspace.database import WorkspaceDatabase
from src.workspace.jobs import queue
from src.workspace.models import Base, Job, User


@pytest.fixture
def jobs():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    owner = uuid.uuid4()
    job_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(User(id=owner, password_hash="example"))
        session.flush()
        session.add(Job(id=job_id, owner_id=owner, kind="import", payload={"source": "example"}))
    yield database, job_id
    database.close()


def test_claim_renew_and_finish(jobs, monkeypatch):
    database, job_id = jobs
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(queue, "_now", lambda: now)
    first = queue.claim_job(database, kinds=("import",), lease=timedelta(minutes=1))
    assert first is not None and first.id == job_id and first.attempts == 1
    assert queue.claim_job(database, kinds=("import",), lease=timedelta(minutes=1)) is None
    assert not queue.renew_lease(database, job_id, uuid.uuid4(), lease=timedelta(minutes=1))
    assert queue.renew_lease(database, job_id, first.lease_token, lease=timedelta(minutes=2))
    assert queue.finish_job(database, job_id, first.lease_token, success=True)
    assert not queue.finish_job(database, job_id, first.lease_token, success=True)


def test_expired_worker_cannot_finish_after_reclaim(jobs, monkeypatch):
    database, job_id = jobs
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(queue, "_now", lambda: now)
    first = queue.claim_job(database, kinds=("import",), lease=timedelta(minutes=1))
    monkeypatch.setattr(queue, "_now", lambda: now + timedelta(minutes=1))
    second = queue.claim_job(database, kinds=("import",), lease=timedelta(minutes=1))
    assert second is not None and second.attempts == 2 and second.lease_token != first.lease_token
    assert not queue.finish_job(database, job_id, first.lease_token, success=True)
    assert queue.finish_job(database, job_id, second.lease_token, success=False, retryable=True)
    monkeypatch.setattr(queue, "_now", lambda: now + timedelta(minutes=1) + queue.RETRY_DELAY)
    third = queue.claim_job(database, kinds=("import",), lease=timedelta(minutes=1))
    assert third is not None and third.attempts == 3
    assert queue.finish_job(database, job_id, third.lease_token, success=False, retryable=True)
    with database.transaction() as session:
        assert session.get(Job, job_id).status == "failed"


def test_retry_delay_leaves_fresh_jobs_eligible(jobs, monkeypatch):
    database, job_id = jobs
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(queue, '_now', lambda: now)
    failed = queue.claim_job(database, kinds=('import',), lease=timedelta(minutes=1))
    assert queue.finish_job(database, job_id, failed.lease_token, success=False, retryable=True)
    with database.transaction() as session:
        fresh = Job(owner_id=failed.owner_id, kind='import', payload={})
        session.add(fresh)
        session.flush()
        fresh_id = fresh.id
    next_job = queue.claim_job(database, kinds=('import',), lease=timedelta(minutes=1))
    assert next_job.id == fresh_id
    assert queue.finish_job(database, fresh_id, next_job.lease_token, success=True)
    monkeypatch.setattr(queue, '_now', lambda: now + timedelta(seconds=29))
    assert queue.claim_job(database, kinds=('import',), lease=timedelta(minutes=1)) is None
    monkeypatch.setattr(queue, '_now', lambda: now + timedelta(seconds=30))
    retried = queue.claim_job(database, kinds=('import',), lease=timedelta(minutes=1))
    assert retried.id == job_id and retried.attempts == 2


def test_expired_final_attempt_is_failed_and_wrong_kind_ignored(jobs, monkeypatch):
    database, job_id = jobs
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(queue, "_now", lambda: now)
    assert queue.claim_job(database, kinds=("other",), lease=timedelta(seconds=1)) is None
    for offset in range(3):
        monkeypatch.setattr(queue, "_now", lambda offset=offset: now + timedelta(seconds=offset))
        assert queue.claim_job(database, kinds=("import",), lease=timedelta(seconds=1)) is not None
    monkeypatch.setattr(queue, "_now", lambda: now + timedelta(seconds=3))
    assert queue.claim_job(database, kinds=("import",), lease=timedelta(seconds=1)) is None
    with database.transaction() as session:
        assert session.get(Job, job_id).status == "failed"
