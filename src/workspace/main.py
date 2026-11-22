"""Separate API entry point for the research workspace."""

from collections.abc import Callable
from contextlib import asynccontextmanager
import logging
import json
from time import perf_counter
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from src.workspace.database import DatabaseConfigurationError, WorkspaceDatabase
from src.workspace.auth.clients import client_key
from src.workspace.auth.origins import has_trusted_origin
from src.workspace.auth.routes import router as auth_router
from src.workspace.auth.settings import AuthSettings, LOGIN_POLICY, load_auth_settings
from src.workspace.auth.throttling import record_invalid_login
from src.workspace.library.routes import router as library_router
from src.workspace.library.source_routes import router as source_router
from src.workspace.library.question_routes import router as question_router
from src.workspace.library.analysis_routes import router as analysis_router
from src.workspace.library.research_routes import router as research_router
from src.workspace.status import router as status_router


logger = logging.getLogger(__name__)


def create_app(
    database_factory: Callable[[], WorkspaceDatabase] = WorkspaceDatabase,
    auth_settings_factory: Callable[[], AuthSettings] = load_auth_settings,
) -> FastAPI:
    """Create the workspace API without loading the legacy application."""

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.auth_settings = auth_settings_factory()
        application.state.database = database_factory()
        try:
            yield
        finally:
            application.state.database.close()

    application = FastAPI(
        title="Research Workspace API",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    application.include_router(analysis_router)
    application.include_router(research_router)
    application.include_router(status_router)

    @application.middleware('http')
    async def request_metrics(request: Request, call_next):
        identity = uuid.uuid4().hex
        started = perf_counter()
        response = await call_next(request)
        route = request.scope.get('route')
        # Log the route template, never query strings, bodies, credentials or prompts.
        logging.getLogger('uvicorn.error').info(json.dumps({'event': 'workspace_request',
            'request_id': identity, 'method': request.method, 'route': getattr(route, 'path', 'unmatched'),
            'status': response.status_code, 'elapsed_ms': round((perf_counter() - started) * 1000, 2)}))
        response.headers['X-Request-ID'] = identity
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        if request.method == "POST" and request.url.path == "/api/v2/auth/login":
            if not has_trusted_origin(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Request origin is not allowed."},
                    headers={"Cache-Control": "no-store"},
                )
            try:
                retry_after = await run_in_threadpool(
                    record_invalid_login,
                    request.app.state.database,
                    client_key=client_key(request),
                    policy=LOGIN_POLICY,
                )
            except (DatabaseConfigurationError, SQLAlchemyError, OSError):
                logger.warning("Workspace sign-in could not access the database.")
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Unable to sign in right now."},
                    headers={"Cache-Control": "no-store"},
                )
            if retry_after is not None:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many sign-in attempts. Try again later."},
                    headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
                )
        details = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details}, headers={"Cache-Control": "no-store"})

    application.include_router(auth_router)
    application.include_router(library_router)
    application.include_router(source_router)
    application.include_router(question_router)

    @application.get("/api/v2/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/v2/ready")
    def ready(request: Request):
        try:
            request.app.state.database.check()
        except (DatabaseConfigurationError, SQLAlchemyError, OSError):
            logger.warning("Workspace database readiness check failed.")
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "database": "unavailable"},
            )
        return {"status": "ready", "database": "ready"}

    return application


app = create_app()
