"""Persistent, transaction-scoped sign-in attempt limits."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.workspace.database import WorkspaceDatabase
from src.workspace.models import LoginThrottle


@dataclass(frozen=True)
class ThrottlePolicy:
    account_limit: int
    client_limit: int
    window: timedelta
    block_duration: timedelta

    def __post_init__(self) -> None:
        if self.account_limit < 1 or self.client_limit < 1:
            raise ValueError("Attempt limits must be positive.")
        if self.window <= timedelta(0) or self.block_duration <= timedelta(0):
            raise ValueError("Throttle durations must be positive.")


@dataclass(frozen=True)
class ThrottleResult:
    verified: bool
    retry_after: int | None = None


def _digest(value: str) -> str:
    # Unknown login identifiers can contain malformed Unicode. They are still
    # counted without ever storing the supplied value or raising an encoding error.
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _utc(value: datetime) -> datetime:
    # SQLite omits timezone information in tests; PostgreSQL returns aware UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _locked_counter(session: Session, scope: str, value: str, now: datetime) -> LoginThrottle:
    digest = _digest(value)
    statement = select(LoginThrottle).where(
        LoginThrottle.scope == scope,
        LoginThrottle.key_digest == digest,
    ).with_for_update()
    counter = session.scalar(statement)
    if counter is not None:
        return counter

    try:
        with session.begin_nested():
            session.add(LoginThrottle(
                scope=scope,
                key_digest=digest,
                attempts=0,
                window_started_at=now,
                updated_at=now,
            ))
            session.flush()
    except IntegrityError:
        # Another transaction may have inserted the same counter first.
        counter = session.scalar(statement)
        if counter is None:
            raise
        return counter

    counter = session.scalar(statement)
    if counter is None:
        raise RuntimeError("Could not create a login throttle counter.")
    return counter


def _remaining_block(counter: LoginThrottle, now: datetime, window: timedelta) -> int | None:
    if counter.blocked_until is not None:
        until = _utc(counter.blocked_until)
        if until > now:
            return max(1, math.ceil((until - now).total_seconds()))
        counter.attempts = 0
        counter.window_started_at = now
        counter.blocked_until = None
    elif now - _utc(counter.window_started_at) >= window:
        counter.attempts = 0
        counter.window_started_at = now
    return None


def check_client_attempt(
    session: Session,
    *,
    client_key: str,
    policy: ThrottlePolicy,
    now: datetime,
) -> int | None:
    """Count one request against its locked client counter."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Throttle time must be timezone-aware.")
    now = now.astimezone(timezone.utc)
    client = _locked_counter(session, "client", client_key, now)
    remaining = _remaining_block(client, now, policy.window)
    client.updated_at = now
    if remaining is not None:
        return remaining
    client.attempts += 1
    if client.attempts >= policy.client_limit:
        client.blocked_until = now + policy.block_duration
    return None


def record_invalid_login(database: WorkspaceDatabase, *, client_key: str, policy: ThrottlePolicy) -> int | None:
    """Count a login request that failed input validation before the route ran."""
    with database.transaction() as session:
        return check_client_attempt(
            session,
            client_key=client_key,
            policy=policy,
            now=datetime.now(timezone.utc),
        )


def check_login_attempt(
    session: Session,
    *,
    principal_scope: str,
    principal_key: str,
    client_key: str,
    verify: Callable[[], bool],
    policy: ThrottlePolicy,
    now: datetime,
) -> ThrottleResult:
    """Verify once under locked client and account counters in an open transaction."""
    if principal_scope not in {"account", "unknown"}:
        raise ValueError("Invalid principal scope.")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Throttle time must be timezone-aware.")
    now = now.astimezone(timezone.utc)

    # Always lock the client first; blocked clients cannot create account rows.
    remaining = check_client_attempt(session, client_key=client_key, policy=policy, now=now)
    if remaining is not None:
        return ThrottleResult(verified=False, retry_after=remaining)

    principal = _locked_counter(session, principal_scope, principal_key, now)
    remaining = _remaining_block(principal, now, policy.window)
    principal.updated_at = now
    if remaining is not None:
        return ThrottleResult(verified=False, retry_after=remaining)

    if verify():
        principal.attempts = 0
        principal.window_started_at = now
        principal.blocked_until = None
        return ThrottleResult(verified=True)

    principal.attempts += 1
    if principal.attempts >= policy.account_limit:
        principal.blocked_until = now + policy.block_duration
    return ThrottleResult(verified=False)
