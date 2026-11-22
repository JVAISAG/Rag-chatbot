"""Account registration checks for the workspace API."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from src.workspace.auth.passwords import verify_password
from src.workspace.database import DatabaseConfigurationError, WorkspaceDatabase
from src.workspace.main import create_app
from src.workspace.models import Base, User, UserIdentifier


@pytest.fixture
def registration_api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    with TestClient(create_app(lambda: database), headers={"origin": "http://localhost:3000"}) as client:
        yield client, database


@pytest.mark.parametrize(
    ("identifiers", "expected"),
    [
        ({"username": "Reader_1"}, {"username": "reader_1"}),
        ({"email": "Sam@Example.com"}, {"email": "sam@example.com"}),
        ({"username": "Writer.1", "email": "Writer@Example.com"},
         {"username": "writer.1", "email": "writer@example.com"}),
    ],
)
def test_registration_saves_account_with_hashed_password(registration_api, identifiers, expected):
    client, database = registration_api
    password = "test password with spaces"

    response = client.post("/api/v2/auth/register", json={**identifiers, "password": password})

    assert response.status_code == 201
    assert set(response.json()) == {"id"}
    assert password not in response.text
    assert "set-cookie" not in response.headers
    user_id = uuid.UUID(response.json()["id"])
    with database.transaction() as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.password_hash != password
        assert verify_password(password, user.password_hash).valid
        rows = session.scalars(select(UserIdentifier).where(UserIdentifier.user_id == user_id)).all()
        assert {row.kind: row.normalized_value for row in rows} == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"password": "private-password"},
        {"username": "ab", "password": "private-password"},
        {"username": "r" * 33, "password": "private-password"},
        {"username": "bad name", "password": "private-password"},
        {"username": "José", "password": "private-password"},
        {"email": "not-an-email", "password": "private-password"},
        {"username": "reader", "password": "short"},
        {"username": "reader", "password": "x" * 129},
        {"username": "reader", "password": "private-password", "unexpected": True},
    ],
)
def test_invalid_registration_is_rejected_without_echoing_password(registration_api, payload):
    client, database = registration_api

    response = client.post("/api/v2/auth/register", json=payload)

    assert response.status_code == 422
    assert payload["password"] not in response.text
    with database.transaction() as session:
        assert session.scalars(select(User)).all() == []


def test_password_boundaries_and_unicode_are_accepted(registration_api):
    client, _ = registration_api

    first = client.post("/api/v2/auth/register", json={"username": "abc", "password": "é" * 8})
    second = client.post("/api/v2/auth/register", json={"username": "b" * 32, "password": "x" * 128})

    assert first.status_code == 201
    assert second.status_code == 201


def test_database_failure_does_not_expose_details():
    database = MagicMock()
    database.transaction.side_effect = DatabaseConfigurationError("private-database-details")
    password = "private-password"

    with TestClient(create_app(lambda: database), headers={"origin": "http://localhost:3000"}) as client:
        response = client.post("/api/v2/auth/register", json={"username": "reader", "password": password})

    assert response.status_code == 503
    assert "private-database-details" not in response.text
    assert password not in response.text


@pytest.mark.parametrize(
    ("constraint", "expected_status"),
    [("uq_user_identifiers_normalized_value", 409), ("unrelated_constraint", 503)],
)
def test_identifier_conflicts_are_handled_without_leaking_details(constraint, expected_status, caplog):
    class DriverError(Exception):
        sqlstate = "23505"
        diag = SimpleNamespace(constraint_name=constraint)

    @contextmanager
    def failing_transaction():
        yield MagicMock()
        raise IntegrityError("private-statement", {}, DriverError("private-database-details"))

    database = MagicMock()
    database.transaction.side_effect = failing_transaction
    password = "private-password"
    with TestClient(create_app(lambda: database), headers={"origin": "http://localhost:3000"}) as client:
        response = client.post("/api/v2/auth/register", json={"username": "Reader", "password": password})

    assert response.status_code == expected_status
    assert "private-database-details" not in response.text
    assert "private-statement" not in response.text
    assert password not in response.text
    assert password not in caplog.text
