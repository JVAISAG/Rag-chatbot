"""Credential verification shared by the workspace sign-in flow."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event

from src.workspace.auth import login
from src.workspace.auth.passwords import hash_password
from src.workspace.auth.throttling import ThrottlePolicy
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import Base, User, UserIdentifier


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
POLICY = ThrottlePolicy(2, 20, timedelta(minutes=15), timedelta(minutes=15))
PASSWORD = "secure password with spaces 🐈"


@pytest.fixture
def account_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def disable_driver_transaction_control(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    user_id = uuid.uuid4()
    with database.transaction() as session:
        session.add(User(id=user_id, password_hash=hash_password(PASSWORD)))
        session.add_all([
            UserIdentifier(user_id=user_id, kind="username", value="Reader", normalized_value="reader"),
            UserIdentifier(user_id=user_id, kind="email", value="Reader@example.com", normalized_value="reader@example.com"),
        ])
    try:
        yield database, user_id
    finally:
        database.close()


def authenticate(database, identifier, password, *, client="127.0.0.1"):
    return login.authenticate_password(
        database,
        login.LoginRequest(identifier=identifier, password=password),
        client_key=client,
        policy=POLICY,
        now=NOW,
    )


def test_sign_in_accepts_case_insensitive_username_and_email(account_database):
    database, user_id = account_database
    assert authenticate(database, "READER", PASSWORD).user_id == user_id
    assert authenticate(database, "reader@EXAMPLE.COM", PASSWORD).user_id == user_id
    assert authenticate(database, "Reader", " " + PASSWORD).user_id is None


def test_wrong_password_and_unknown_identifier_have_the_same_result(account_database):
    database, _ = account_database
    wrong_password = authenticate(database, "Reader", "wrong-password")
    unknown_account = authenticate(database, "nobody@example.com", "wrong-password")
    malformed_identifier = authenticate(database, "this is not a username", "wrong-password")
    assert wrong_password == unknown_account == malformed_identifier == login.LoginResult()


def test_failure_limit_is_shared_between_email_and_username(account_database):
    database, _ = account_database
    assert authenticate(database, "Reader", "wrong", client="first").retry_after is None
    assert authenticate(database, "reader@example.com", "wrong", client="second").retry_after is None
    blocked = authenticate(database, "READER", PASSWORD, client="third")
    assert blocked.user_id is None
    assert blocked.retry_after == 900


def test_dummy_hash_match_never_authenticates_an_unknown_identifier(account_database, monkeypatch):
    database, _ = account_database
    monkeypatch.setattr(login, "_dummy_password_hash", lambda: hash_password(PASSWORD))
    assert authenticate(database, "unknown", PASSWORD).user_id is None


def test_equivalent_unknown_emails_share_a_failure_limit(account_database):
    database, _ = account_database
    assert authenticate(database, "sam@bücher.de", "wrong").retry_after is None
    assert authenticate(database, "SAM@xn--bcher-kva.de", "wrong").retry_after is None
    assert authenticate(database, "sam@bücher.de", "wrong").retry_after == 900


def test_login_input_preserves_password_and_does_not_display_it():
    password = "🦊 " * 64
    request = login.LoginRequest(identifier="Reader", password=password)
    assert request.password.get_secret_value() == password
    assert password not in repr(request)
    assert login.LoginRequest(identifier="Reader", password="").password.get_secret_value() == ""


@pytest.mark.parametrize("identifier,password", [
    ("", "valid"),
    ("x" * 321, "valid"),
    ("Reader", "x" * 129),
    ("\ud800", "valid"),
    ("Reader", "\ud800"),
])
def test_invalid_login_input_is_rejected(identifier, password):
    with pytest.raises(ValidationError):
        login.LoginRequest(identifier=identifier, password=password)
