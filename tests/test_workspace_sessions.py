"""Session storage and lifecycle checks."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from src.workspace.auth import sessions
from src.workspace.auth.session_tokens import session_token_digest
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import Base, User, UserSession


@pytest.fixture
def session_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    try:
        yield database
    finally:
        database.close()


def add_user(database: WorkspaceDatabase) -> uuid.UUID:
    user_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(User(id=user_id, password_hash="example-hash"))
    return user_id


def test_sessions_store_only_token_hashes_and_allow_multiple_devices(session_database):
    user_id = add_user(session_database)
    first = sessions.issue_session(session_database, user_id)
    second = sessions.issue_session(session_database, user_id)

    assert first.token != second.token
    assert first.token not in repr(first)
    assert sessions.resolve_session(session_database, first.token) == user_id
    assert sessions.resolve_session(session_database, second.token) == user_id
    with session_database.transaction() as session:
        records = session.scalars(select(UserSession)).all()
        assert {record.token_hash for record in records} == {
            session_token_digest(first.token), session_token_digest(second.token),
        }
        assert all(record.token_hash not in {first.token, second.token} for record in records)


def test_session_expires_exactly_seven_days_after_issue(session_database, monkeypatch):
    user_id = add_user(session_database)
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sessions, "_utc_now", lambda: now)
    issued = sessions.issue_session(session_database, user_id)

    assert issued.expires_at == now + timedelta(days=7)
    monkeypatch.setattr(sessions, "_utc_now", lambda: issued.expires_at - timedelta(microseconds=1))
    assert sessions.resolve_session(session_database, issued.token) == user_id
    monkeypatch.setattr(sessions, "_utc_now", lambda: issued.expires_at)
    assert sessions.resolve_session(session_database, issued.token) is None


def test_revoking_one_session_does_not_revoke_others(session_database):
    first_user = add_user(session_database)
    second_user = add_user(session_database)
    first = sessions.issue_session(session_database, first_user)
    second = sessions.issue_session(session_database, first_user)
    other = sessions.issue_session(session_database, second_user)

    assert sessions.revoke_session(session_database, first.token)
    assert not sessions.revoke_session(session_database, first.token)
    assert sessions.resolve_session(session_database, first.token) is None
    assert sessions.resolve_session(session_database, second.token) == first_user
    assert sessions.resolve_session(session_database, other.token) == second_user


def test_invalid_tokens_do_not_query_database():
    database = MagicMock()

    assert sessions.resolve_session(database, "invalid") is None
    assert not sessions.revoke_session(database, None)
    database.transaction.assert_not_called()


def test_failed_session_insert_does_not_replace_existing_session(session_database, monkeypatch):
    user_id = add_user(session_database)
    fixed_token = "a" * 43
    monkeypatch.setattr(sessions, "generate_session_token", lambda: fixed_token)
    first = sessions.issue_session(session_database, user_id)

    with pytest.raises(IntegrityError):
        sessions.issue_session(session_database, user_id)

    assert sessions.resolve_session(session_database, first.token) == user_id
    with session_database.transaction() as session:
        assert len(session.scalars(select(UserSession)).all()) == 1


def test_session_cannot_be_issued_for_unknown_user(session_database):
    with pytest.raises(IntegrityError):
        sessions.issue_session(session_database, uuid.uuid4())
