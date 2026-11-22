"""Create, validate, and revoke workspace sessions."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select, update

from src.workspace.auth.session_tokens import generate_session_token, session_token_digest
from src.workspace.database import WorkspaceDatabase
from src.workspace.models import UserSession


SESSION_LIFETIME = timedelta(days=7)


@dataclass(frozen=True)
class IssuedSession:
    """A new session token and its fixed expiration time."""

    token: str = field(repr=False)
    expires_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def issue_session(database: WorkspaceDatabase, user_id: uuid.UUID) -> IssuedSession:
    """Create a session for an authenticated user; return its token after commit."""
    token = generate_session_token()
    digest = session_token_digest(token)
    if digest is None:
        raise RuntimeError("Could not generate a valid session token.")
    expires_at = _utc_now() + SESSION_LIFETIME

    with database.transaction() as session:
        session.add(UserSession(user_id=user_id, token_hash=digest, expires_at=expires_at))

    return IssuedSession(token=token, expires_at=expires_at)


def resolve_session(database: WorkspaceDatabase, token: str | None) -> uuid.UUID | None:
    """Return the owner of a valid, unexpired, unrevoked session."""
    digest = session_token_digest(token)
    if digest is None:
        return None

    with database.transaction() as session:
        return session.scalar(
            select(UserSession.user_id).where(
                UserSession.token_hash == digest,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > _utc_now(),
            )
        )


def revoke_session(database: WorkspaceDatabase, token: str | None) -> bool:
    """Revoke one session, returning whether it was newly revoked."""
    digest = session_token_digest(token)
    if digest is None:
        return False

    with database.transaction() as session:
        result = session.execute(
            update(UserSession)
            .where(UserSession.token_hash == digest, UserSession.revoked_at.is_(None))
            .values(revoked_at=_utc_now())
        )
        return result.rowcount == 1
