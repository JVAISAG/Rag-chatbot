"""Set and clear opaque browser session cookies."""

from starlette.responses import Response

from src.workspace.auth.sessions import IssuedSession, SESSION_LIFETIME


SESSION_COOKIE = "workspace_session"


def set_session_cookie(response: Response, session: IssuedSession, *, secure: bool) -> None:
    """Keep the raw session token out of response bodies and JavaScript."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session.token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        expires=session.expires_at,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
