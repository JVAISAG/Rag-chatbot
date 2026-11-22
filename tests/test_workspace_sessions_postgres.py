"""Opt-in PostgreSQL checks for workspace sessions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import re
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import NullPool

from src.workspace.auth import sessions
from src.workspace.auth.session_tokens import session_token_digest
from src.workspace.database import WorkspaceDatabase, database_url
from src.workspace.models import Base, User, UserSession


@pytest.mark.skipif(
    os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1",
    reason="Set WORKSPACE_RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests.",
)
def test_postgres_multiple_sessions_expiration_and_revocation(monkeypatch):
    url = database_url()
    if url.host not in {"127.0.0.1", "localhost"} or not re.fullmatch(r"research_test_[0-9a-f]{12}", url.database or ""):
        pytest.fail("PostgreSQL session tests require a dedicated local research_test_<12 hex digits> database.")

    schema = f"workspace_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    workspace_engine = None
    database = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        workspace_engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema},public"},
        )
        Base.metadata.create_all(workspace_engine)
        database = WorkspaceDatabase(engine_factory=lambda: workspace_engine)
        user_id = uuid.uuid4()
        with database.transaction() as session:
            session.add(User(id=user_id, password_hash="example-hash"))

        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(sessions, "_utc_now", lambda: now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(lambda _: sessions.issue_session(database, user_id), range(2)))

        assert first.token != second.token
        assert first.expires_at == now + timedelta(days=7)
        assert sessions.resolve_session(database, first.token) == user_id
        assert sessions.resolve_session(database, second.token) == user_id
        with database.transaction() as session:
            records = session.scalars(select(UserSession)).all()
            assert {record.token_hash for record in records} == {
                session_token_digest(first.token), session_token_digest(second.token),
            }
            assert all(record.expires_at.tzinfo is not None for record in records)

        assert sessions.revoke_session(database, first.token)
        assert sessions.resolve_session(database, first.token) is None
        assert sessions.resolve_session(database, second.token) == user_id
        monkeypatch.setattr(sessions, "_utc_now", lambda: second.expires_at)
        assert sessions.resolve_session(database, second.token) is None
    finally:
        if database is not None:
            database.close()
        elif workspace_engine is not None:
            workspace_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()
