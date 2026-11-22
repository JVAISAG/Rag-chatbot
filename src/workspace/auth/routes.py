"""Research workspace account endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from src.workspace.auth.clients import client_key
from src.workspace.auth.cookies import SESSION_COOKIE, clear_session_cookie, set_session_cookie
from src.workspace.auth.dependencies import require_user
from src.workspace.auth.login import LoginRequest, authenticate_password
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.auth.registration import (
    IdentifierUnavailable,
    RegistrationRequest,
    RegistrationResponse,
    register_account,
)
from src.workspace.auth.sessions import issue_session, revoke_session
from src.workspace.auth.settings import LOGIN_POLICY
from src.workspace.database import DatabaseConfigurationError


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/auth", tags=["authentication"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def register(request: Request, details: RegistrationRequest) -> RegistrationResponse:
    try:
        user_id = register_account(request.app.state.database, details)
    except IdentifierUnavailable:
        raise HTTPException(status_code=409, detail="An identifier is unavailable.") from None
    except (DatabaseConfigurationError, SQLAlchemyError, OSError):
        logger.warning("Workspace registration could not access the database.")
        raise HTTPException(status_code=503, detail="Unable to create the account right now.") from None

    return RegistrationResponse(id=user_id)


@router.post("/login", response_model=RegistrationResponse, dependencies=[Depends(require_trusted_origin)])
def login(request: Request, response: Response, details: LoginRequest) -> RegistrationResponse:
    try:
        # Use the actual ASGI peer, never an untrusted forwarding header. The
        # local server must also run with proxy-header processing disabled.
        outcome = authenticate_password(
            request.app.state.database,
            details,
            client_key=client_key(request),
            policy=LOGIN_POLICY,
        )
        if outcome.user_id is not None:
            session = issue_session(request.app.state.database, outcome.user_id)
    except (DatabaseConfigurationError, SQLAlchemyError, OSError):
        logger.warning("Workspace sign-in could not access the database.")
        raise HTTPException(
            status_code=503,
            detail="Unable to sign in right now.",
            headers={"Cache-Control": "no-store"},
        ) from None

    if outcome.retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again later.",
            headers={"Retry-After": str(outcome.retry_after), "Cache-Control": "no-store"},
        )
    if outcome.user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid identifier or password.",
            headers={"Cache-Control": "no-store"},
        )

    set_session_cookie(response, session, secure=request.app.state.auth_settings.cookie_secure)
    return RegistrationResponse(id=outcome.user_id)


@router.get("/me", response_model=RegistrationResponse)
def current_user(response: Response, user_id: uuid.UUID = Depends(require_user)) -> RegistrationResponse:
    response.headers["Cache-Control"] = "no-store"
    return RegistrationResponse(id=user_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_trusted_origin)])
def logout(request: Request) -> Response:
    try:
        revoke_session(request.app.state.database, request.cookies.get(SESSION_COOKIE))
    except (DatabaseConfigurationError, SQLAlchemyError, OSError):
        logger.warning("Workspace logout could not access the database.")
        raise HTTPException(
            status_code=503,
            detail="Unable to sign out right now.",
            headers={"Cache-Control": "no-store"},
        ) from None
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, secure=request.app.state.auth_settings.cookie_secure)
    return response
