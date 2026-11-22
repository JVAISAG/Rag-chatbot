"""Behavior of the persistent login-attempt counters."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select

from src.workspace.auth.throttling import ThrottlePolicy, check_login_attempt
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import Base, LoginThrottle


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
POLICY = ThrottlePolicy(
    account_limit=2,
    client_limit=6,
    window=timedelta(minutes=15),
    block_duration=timedelta(minutes=15),
)


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    # Make savepoints participate in the outer transaction on SQLite as they do
    # on PostgreSQL. Python's sqlite driver otherwise uses legacy BEGIN rules.
    @event.listens_for(engine, "connect")
    def disable_driver_transaction_control(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    workspace = WorkspaceDatabase(engine_factory=lambda: engine)
    try:
        yield workspace
    finally:
        workspace.close()


def attempt(database, *, principal="account-id", scope="account", client="127.0.0.1", valid=False,
            policy=POLICY, now=NOW, verifier=None):
    with database.transaction() as session:
        return check_login_attempt(
            session,
            principal_scope=scope,
            principal_key=principal,
            client_key=client,
            verify=verifier or (lambda: valid),
            policy=policy,
            now=now,
        )


def test_account_is_blocked_after_the_failure_limit_and_recovers(database):
    assert not attempt(database).verified
    assert not attempt(database).verified

    def should_not_verify():
        pytest.fail("A blocked request must not verify a password.")

    blocked = attempt(database, valid=True, verifier=should_not_verify)
    assert blocked.retry_after == 900
    almost_ready = attempt(database, now=NOW + timedelta(seconds=899, microseconds=1))
    assert almost_ready.retry_after == 1
    assert attempt(database, valid=True, now=NOW + timedelta(minutes=15)).verified


def test_success_clears_account_failures(database):
    attempt(database)
    assert attempt(database, valid=True).verified
    assert attempt(database).retry_after is None
    assert attempt(database, valid=True).verified


def test_client_limit_counts_successful_attempts_and_stops_new_counter_creation(database):
    policy = ThrottlePolicy(2, 2, timedelta(minutes=15), timedelta(minutes=15))
    assert attempt(database, principal="first", valid=True, policy=policy).verified
    assert attempt(database, principal="second", valid=True, policy=policy).verified
    blocked = attempt(database, principal="third", valid=True, policy=policy)
    assert blocked.retry_after == 900

    with database.transaction() as session:
        counters = session.scalars(select(LoginThrottle)).all()
        assert len(counters) == 3  # One client and the first two accounts.
        assert {counter.scope for counter in counters} == {"account", "client"}


def test_failure_window_resets_without_a_block(database):
    attempt(database)
    assert attempt(database, now=NOW + timedelta(minutes=15)).retry_after is None
    assert attempt(database, valid=True, now=NOW + timedelta(minutes=15)).verified


def test_unknown_identifiers_are_limited_and_keys_are_stored_as_digests(database):
    attempt(database, principal="private@example.com", scope="unknown", client="192.0.2.17")
    attempt(database, principal="private@example.com", scope="unknown", client="192.0.2.17")
    assert attempt(database, principal="private@example.com", scope="unknown", client="192.0.2.17").retry_after == 900

    with database.transaction() as session:
        counters = session.scalars(select(LoginThrottle)).all()
        assert {counter.scope for counter in counters} == {"unknown", "client"}
        assert all(len(counter.key_digest) == 64 for counter in counters)
        assert all(counter.key_digest not in {"private@example.com", "192.0.2.17"} for counter in counters)


def test_verification_exception_rolls_back_counters(database):
    def fail_verification():
        raise RuntimeError("verification unavailable")

    with pytest.raises(RuntimeError, match="verification unavailable"):
        attempt(database, verifier=fail_verification)
    with database.transaction() as session:
        assert session.scalars(select(LoginThrottle)).all() == []


@pytest.mark.parametrize("account_limit,client_limit,window,block_duration", [
    (0, 1, timedelta(minutes=1), timedelta(minutes=1)),
    (1, 0, timedelta(minutes=1), timedelta(minutes=1)),
    (1, 1, timedelta(0), timedelta(minutes=1)),
    (1, 1, timedelta(minutes=1), timedelta(0)),
])
def test_invalid_policy_is_rejected(account_limit, client_limit, window, block_duration):
    with pytest.raises(ValueError):
        ThrottlePolicy(account_limit, client_limit, window, block_duration)


def test_invalid_scope_and_naive_times_are_rejected(database):
    with pytest.raises(ValueError, match="scope"):
        attempt(database, scope="client")
    with pytest.raises(ValueError, match="timezone"):
        attempt(database, now=NOW.replace(tzinfo=None))
