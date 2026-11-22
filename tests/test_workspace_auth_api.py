"""End-to-end account and browser-session behavior through the workspace API."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from src.workspace.auth import login as login_service, routes, sessions
from src.workspace.auth.cookies import SESSION_COOKIE
from src.workspace.auth.passwords import PasswordVerification
from src.workspace.auth.session_tokens import session_token_digest
from src.workspace.auth.settings import AuthSettings
from src.workspace.database import DatabaseConfigurationError, WorkspaceDatabase
from src.workspace.main import create_app
from src.workspace.models import Base, LoginThrottle, UserSession


ORIGIN = {"origin": "http://localhost:3000"}
PASSWORD = "test password with spaces 🐈"


@pytest.fixture
def auth_api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    app = create_app(lambda: database, lambda: AuthSettings(cookie_secure=False))
    with TestClient(app, base_url="http://localhost:8001") as client:
        yield client, database


def register(client, *, username="Reader", email="reader@example.com"):
    response = client.post(
        "/api/v2/auth/register",
        json={"username": username, "email": email, "password": PASSWORD},
        headers=ORIGIN,
    )
    assert response.status_code == 201
    assert "set-cookie" not in response.headers
    return response.json()["id"]


def sign_in(client, identifier="Reader", password=PASSWORD, headers=ORIGIN):
    return client.post(
        "/api/v2/auth/login",
        json={"identifier": identifier, "password": password},
        headers=headers,
    )


def use_cookie(client, token):
    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE, token)


def test_registration_login_multiple_sessions_and_logout(auth_api):
    client, database = auth_api
    user_id = register(client)
    assert client.get("/api/v2/auth/me").status_code == 401

    first = sign_in(client, "READER@EXAMPLE.COM")
    assert first.status_code == 200
    assert first.json() == {"id": user_id}
    first_token = client.cookies[SESSION_COOKIE]
    assert PASSWORD not in first.text and first_token not in first.text
    assert "httponly" in first.headers["set-cookie"].lower()
    assert "samesite=lax" in first.headers["set-cookie"].lower()
    assert first.headers["cache-control"] == "no-store"
    assert client.get("/api/v2/auth/me").json() == {"id": user_id}

    client.cookies.clear()
    second = sign_in(client, "reader")
    second_token = client.cookies[SESSION_COOKIE]
    assert second.status_code == 200
    assert first_token != second_token

    use_cookie(client, first_token)
    assert client.get("/api/v2/auth/me").json() == {"id": user_id}
    logout = client.post("/api/v2/auth/logout", headers=ORIGIN)
    assert logout.status_code == 204
    assert logout.content == b""
    assert logout.headers["cache-control"] == "no-store"
    assert client.get("/api/v2/auth/me").status_code == 401
    use_cookie(client, first_token)
    assert client.get("/api/v2/auth/me").status_code == 401
    use_cookie(client, second_token)
    assert client.get("/api/v2/auth/me").json() == {"id": user_id}

    with database.transaction() as session:
        records = session.scalars(select(UserSession)).all()
        assert {record.token_hash for record in records} == {
            session_token_digest(first_token), session_token_digest(second_token),
        }
        assert all(record.token_hash not in {first_token, second_token} for record in records)
        assert sum(record.revoked_at is not None for record in records) == 1


def test_sessions_identify_the_correct_account_and_expire_after_seven_days(auth_api, monkeypatch):
    client, _ = auth_api
    first_user = register(client)
    second_user = register(client, username="Writer", email="writer@example.com")
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(sessions, "_utc_now", lambda: now)

    assert sign_in(client).json() == {"id": first_user}
    first_token = client.cookies[SESSION_COOKIE]
    client.cookies.clear()
    assert sign_in(client, "Writer").json() == {"id": second_user}
    assert client.get("/api/v2/auth/me").json() == {"id": second_user}
    use_cookie(client, first_token)
    assert client.get("/api/v2/auth/me").json() == {"id": first_user}

    monkeypatch.setattr(sessions, "_utc_now", lambda: now + timedelta(days=7))
    assert client.get("/api/v2/auth/me").status_code == 401


def test_wrong_password_and_unknown_account_have_the_same_response(auth_api, caplog):
    client, _ = auth_api
    register(client)
    wrong = sign_in(client, "Reader", "a private wrong password")
    unknown = sign_in(client, "Nobody", "a private wrong password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid identifier or password."}
    assert "set-cookie" not in wrong.headers and "set-cookie" not in unknown.headers
    assert "a private wrong password" not in wrong.text + unknown.text + caplog.text


def test_login_validation_does_not_echo_password(auth_api):
    client, _ = auth_api
    password = "private-secret-" * 20
    response = sign_in(client, password=password)
    assert response.status_code == 422
    assert password not in response.text
    assert "set-cookie" not in response.headers


def test_secure_cookie_is_used_when_http_mode_is_not_enabled(auth_api):
    client, database = auth_api
    user_id = register(client)
    app = create_app(lambda: database, lambda: AuthSettings())
    with TestClient(app, base_url="https://localhost:8001") as secure_client:
        response = sign_in(secure_client)
        assert response.status_code == 200
        assert "; secure" in response.headers["set-cookie"].lower()
        assert secure_client.get("/api/v2/auth/me").json() == {"id": user_id}


def test_account_limit_covers_both_identifiers(auth_api):
    client, _ = auth_api
    register(client)
    for index in range(5):
        identifier = "Reader" if index % 2 else "reader@example.com"
        assert sign_in(client, identifier, "wrong-password").status_code == 401
    blocked = sign_in(client, "READER")
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 900
    assert "set-cookie" not in blocked.headers


def test_client_limit_counts_successes_and_ignores_forwarding_headers(auth_api, monkeypatch):
    client, _ = auth_api
    register(client)
    monkeypatch.setattr(login_service, "verify_password", lambda *_: PasswordVerification(valid=True))
    for index in range(30):
        headers = {**ORIGIN, "x-forwarded-for": f"192.0.2.{index + 1}"}
        assert sign_in(client, headers=headers).status_code == 200
    blocked = sign_in(client, headers={**ORIGIN, "x-forwarded-for": "192.0.2.100"})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 900


def test_client_limit_includes_invalid_fields_and_malformed_json(auth_api):
    client, _ = auth_api
    register(client)
    for index in range(30):
        if index % 2:
            response = client.post(
                "/api/v2/auth/login",
                headers={**ORIGIN, "content-type": "application/json"},
                content=b'{"identifier":',
            )
        else:
            response = sign_in(client, password="x" * 129)
        assert response.status_code == 422
    blocked = sign_in(client)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["retry-after"]) <= 900


@pytest.mark.parametrize("path,payload", [
    ("/api/v2/auth/register", {"username": "Reader", "password": PASSWORD}),
    ("/api/v2/auth/login", {"identifier": "Reader", "password": PASSWORD}),
    ("/api/v2/auth/logout", {}),
])
@pytest.mark.parametrize("headers", [
    {},
    {"origin": "null"},
    {"origin": "http://localhost:3000.evil.example"},
    {"origin": "http://evil.example", "referer": "http://localhost:3000/page"},
])
def test_mutations_reject_missing_or_untrusted_origins(auth_api, path, payload, headers):
    client, database = auth_api
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    with database.transaction() as session:
        assert session.scalars(select(LoginThrottle)).all() == []


def test_both_selected_origins_and_a_trusted_referer_are_allowed(auth_api):
    client, _ = auth_api
    for index, headers in enumerate([
        {"origin": "http://localhost:3000"},
        {"origin": "http://127.0.0.1:3000"},
        {"referer": "http://localhost:3000/register"},
    ]):
        response = client.post(
            "/api/v2/auth/register",
            json={"username": f"reader{index}", "password": PASSWORD},
            headers=headers,
        )
        assert response.status_code == 201


def test_untrusted_origin_cannot_log_out_an_existing_session(auth_api):
    client, _ = auth_api
    user_id = register(client)
    assert sign_in(client).status_code == 200
    response = client.post("/api/v2/auth/logout", headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert client.get("/api/v2/auth/me").json() == {"id": user_id}


def test_malformed_cross_origin_login_is_rejected_before_counting(auth_api):
    client, database = auth_api
    response = client.post(
        "/api/v2/auth/login",
        headers={"origin": "http://evil.example", "content-type": "application/json"},
        content=b'{"identifier":',
    )
    assert response.status_code == 403
    with database.transaction() as session:
        assert session.scalars(select(LoginThrottle)).all() == []


def test_selected_loopback_origin_can_log_in_and_log_out(auth_api):
    client, _ = auth_api
    register(client)
    headers = {"origin": "http://127.0.0.1:3000"}
    assert sign_in(client, headers=headers).status_code == 200
    assert client.post("/api/v2/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v2/auth/me").status_code == 401


def test_failure_to_issue_session_does_not_return_a_cookie(auth_api, monkeypatch):
    client, database = auth_api
    register(client)

    def fail_to_issue(*_):
        raise DatabaseConfigurationError("private database details")

    monkeypatch.setattr(routes, "issue_session", fail_to_issue)
    response = sign_in(client)
    assert response.status_code == 503
    assert "private database details" not in response.text
    assert "set-cookie" not in response.headers
    assert client.get("/api/v2/auth/me").status_code == 401
    with database.transaction() as session:
        assert session.scalars(select(UserSession)).all() == []


@pytest.mark.parametrize("method,path", [
    ("post", "/api/v2/auth/login"),
    ("get", "/api/v2/auth/me"),
    ("post", "/api/v2/auth/logout"),
])
def test_database_errors_do_not_expose_secrets(method, path):
    database = MagicMock()
    database.transaction.side_effect = DatabaseConfigurationError("private database details")
    app = create_app(lambda: database, lambda: AuthSettings(cookie_secure=False))
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, "a" * 43)
        response = client.request(method, path, headers=ORIGIN, json={"identifier": "Reader", "password": PASSWORD})
    assert response.status_code == 503
    assert "private database details" not in response.text
    assert PASSWORD not in response.text
    assert "set-cookie" not in response.headers
