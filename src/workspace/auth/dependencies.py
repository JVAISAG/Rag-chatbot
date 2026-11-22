"""Shared authentication checks for protected workspace routes."""

import logging
import uuid

from fastapi import HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from src.workspace.auth.cookies import SESSION_COOKIE
from src.workspace.auth.sessions import resolve_session
from src.workspace.database import DatabaseConfigurationError


logger = logging.getLogger(__name__)


def require_user(request: Request) -> uuid.UUID:
    """Resolve the account from the session cookie, never from request data."""
    try:
        user_id = resolve_session(request.app.state.database, request.cookies.get(SESSION_COOKIE))
    except (DatabaseConfigurationError, SQLAlchemyError, OSError):
        logger.warning("Workspace session lookup could not access the database.")
        raise HTTPException(
            status_code=503,
            detail="Unable to check the session right now.",
            headers={"Cache-Control": "no-store"},
        ) from None
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated.",
            headers={"Cache-Control": "no-store"},
        )
    return user_id
