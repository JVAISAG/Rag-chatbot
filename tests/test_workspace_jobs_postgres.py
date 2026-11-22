"""Opt-in concurrent PostgreSQL job-claim check."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import re
from threading import Barrier, Event
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from src.workspace.database import WorkspaceDatabase, database_url
from src.workspace.jobs.queue import claim_job
from src.workspace.jobs.worker import Worker
from src.workspace.models import Base, Job, User


@pytest.mark.skipif(os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1", reason="PostgreSQL tests are opt-in.")
def test_concurrent_workers_claim_each_job_only_once(tmp_path, monkeypatch):
    url = database_url()
    if url.host not in {"127.0.0.1", "localhost"} or not re.fullmatch(r"research_test_[0-9a-f]{12}", url.database or ""):
        pytest.fail("A dedicated local research_test_<12 hex digits> database is required.")
    schema = f"workspace_test_{uuid.uuid4().hex}"
    admin = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    engine = None
    database = None
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        engine = create_engine(url, poolclass=NullPool, connect_args={"options": f"-csearch_path={schema},public", "connect_timeout": 3})
        Base.metadata.create_all(engine)
        database = WorkspaceDatabase(engine_factory=lambda: engine)
        owner = uuid.uuid4()
        with database.transaction() as session:
            session.add(User(id=owner, password_hash="example"))
            session.flush()
            session.add_all([Job(owner_id=owner, kind="import", payload={}) for _ in range(2)])
        barrier = Barrier(4)

        def claim(_):
            barrier.wait(timeout=10)
            return claim_job(database, kinds=("import",), lease=timedelta(minutes=1))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(4)))
        claimed = [item for item in results if item is not None]
        assert len(claimed) == 2
        assert len({item.id for item in claimed}) == 2
        job_id = uuid.uuid4()
        with database.transaction() as session:
            session.add(Job(id=job_id, owner_id=owner, kind="check", payload={"value": 1}))
        seen = []
        def handle(job, context):
            context.ensure_active()
            seen.append(job.payload["value"])
        assert Worker(database, {"check": handle}).run_once()
        assert seen == [1]
        with database.transaction() as session:
            assert session.get(Job, job_id).status == "completed"

        from src.workspace.jobs import queue
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        monkeypatch.setattr(queue, '_now', lambda: now)
        retry_id = uuid.uuid4()
        with database.transaction() as session:
            session.add(Job(id=retry_id, owner_id=owner, kind='retry', payload={}))
        first = queue.claim_job(database, kinds=('retry',), lease=timedelta(minutes=1))
        assert queue.finish_job(database, retry_id, first.lease_token, success=False, retryable=True)
        assert queue.claim_job(database, kinds=('retry',), lease=timedelta(minutes=1)) is None
        monkeypatch.setattr(queue, '_now', lambda: now + queue.RETRY_DELAY)
        retried = queue.claim_job(database, kinds=('retry',), lease=timedelta(minutes=1))
        assert retried.id == retry_id and retried.attempts == 2

        # Even an artificially old file being staged in an uncommitted upload
        # must not be mistaken for an orphan by another process.
        from datetime import datetime, timezone
        from concurrent.futures import TimeoutError
        from src.workspace.library.cleanup import reconcile_storage
        from src.workspace.library.imports import lock_storage
        from src.workspace.models import Source
        started, release, cleaning = Event(), Event(), Event()
        source_id, extract_id = uuid.uuid4(), uuid.uuid4()
        key = source_id.hex + '.txt'
        def stage_in_transaction():
            with database.transaction() as session:
                lock_storage(session)
                target = tmp_path / key
                target.write_text('staged document')
                old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
                os.utime(target, (old, old))
                session.add(Job(id=extract_id, owner_id=owner, kind='extract', payload={}))
                session.flush()
                session.add(Source(id=source_id, owner_id=owner, filename='paper.txt', content_hash='a' * 64,
                    storage_key=key, job_id=extract_id))
                session.flush()
                started.set()
                assert release.wait(15)
        def clean():
            cleaning.set()
            return reconcile_storage(database, tmp_path)
        with ThreadPoolExecutor(max_workers=2) as pool:
            staging = pool.submit(stage_in_transaction)
            try:
                assert started.wait(10)
                cleanup = pool.submit(clean)
                assert cleaning.wait(10)
                with pytest.raises(TimeoutError):
                    cleanup.result(timeout=0.5)
            finally:
                release.set()
            staging.result(timeout=10)
            assert cleanup.result(timeout=10) == 0
        assert (tmp_path / key).read_text() == 'staged document'
    finally:
        if database is not None:
            database.close()
        elif engine is not None:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
