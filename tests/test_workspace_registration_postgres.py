"""Opt-in PostgreSQL checks for concurrent workspace registration."""

from concurrent.futures import ThreadPoolExecutor
import os
import re
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import NullPool

from src.workspace.auth.cookies import SESSION_COOKIE
from src.workspace.auth.passwords import verify_password
from src.workspace.auth.settings import AuthSettings
from src.workspace.database import WorkspaceDatabase, database_url
from src.workspace.main import create_app
from src.workspace.models import Base, User, UserIdentifier


@pytest.mark.skipif(
    os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1",
    reason="Set WORKSPACE_RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests.",
)
def test_postgres_registration_handles_conflicts_and_rollbacks():
    url = database_url()
    if url.host not in {"127.0.0.1", "localhost"} or not re.fullmatch(r"research_test_[0-9a-f]{12}", url.database or ""):
        pytest.fail("PostgreSQL registration tests require a dedicated local research_test_<12 hex digits> database.")

    schema = f"workspace_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    workspace_engine = None
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
        password = "temporary-example-password"

        with TestClient(
            create_app(lambda: database, lambda: AuthSettings(cookie_secure=False)),
            headers={"origin": "http://localhost:3000"},
        ) as client:
            response = client.post("/api/v2/auth/register", json={
                "username": "Reader_1", "email": "Sam@Example.com", "password": password,
            })
            assert response.status_code == 201
            user_id = response.json()["id"]

            duplicate_username = client.post("/api/v2/auth/register", json={
                "username": "reader_1", "email": "new@example.com", "password": password,
            })
            duplicate_email = client.post("/api/v2/auth/register", json={
                "username": "FreshUser", "email": "sam@example.com", "password": password,
            })
            assert duplicate_username.status_code == 409
            assert duplicate_email.status_code == 409

            def register_same_username(_):
                return client.post("/api/v2/auth/register", json={
                    "username": "RaceUser", "password": password,
                }).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(register_same_username, range(2))) == [201, 409]

            with database.transaction() as session:
                assert session.scalar(select(func.count()).select_from(User)) == 2
                assert session.scalar(select(func.count()).select_from(UserIdentifier)) == 3
                assert session.scalar(select(UserIdentifier.id).where(UserIdentifier.normalized_value == "freshuser")) is None
                assert session.scalar(select(UserIdentifier.id).where(UserIdentifier.normalized_value == "new@example.com")) is None
                user = session.scalar(select(User).join(UserIdentifier).where(UserIdentifier.normalized_value == "reader_1"))
                assert user.password_hash != password
                assert verify_password(password, user.password_hash).valid

            by_email = client.post("/api/v2/auth/login", json={
                "identifier": "SAM@example.com", "password": password,
            })
            assert by_email.status_code == 200
            assert by_email.json() == {"id": user_id}
            first_token = client.cookies[SESSION_COOKIE]
            assert client.get("/api/v2/auth/me").json() == {"id": user_id}

            client.cookies.clear()
            by_username = client.post("/api/v2/auth/login", json={
                "identifier": "READER_1", "password": password,
            })
            assert by_username.status_code == 200
            second_token = client.cookies[SESSION_COOKIE]
            assert first_token != second_token
            assert client.post("/api/v2/auth/logout").status_code == 204
            assert client.get("/api/v2/auth/me").status_code == 401
            client.cookies.set(SESSION_COOKIE, first_token)
            assert client.get("/api/v2/auth/me").json() == {"id": user_id}

            # The two successful sign-ins already used two of this client's
            # 30 attempts. Invalid request bodies must count as well.
            for _ in range(28):
                invalid = client.post(
                    "/api/v2/auth/login",
                    headers={"content-type": "application/json"},
                    content=b'{"identifier":',
                )
                assert invalid.status_code == 422
            blocked = client.post("/api/v2/auth/login", json={
                "identifier": "Reader_1", "password": password,
            })
            assert blocked.status_code == 429
            assert client.get("/api/v2/auth/me").json() == {"id": user_id}
    finally:
        if workspace_engine is not None:
            workspace_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()
