"""Lazy PostgreSQL connection for the research workspace."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import os
from pathlib import Path
from threading import Lock

from dotenv import dotenv_values
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
SCHEMA_REVISION = '20261121_01'


class DatabaseConfigurationError(ValueError):
    """The workspace database configuration is missing or invalid."""


def database_url(
    environ: Mapping[str, str] | None = None,
    env_file: Path = DEFAULT_ENV_FILE,
) -> URL:
    """Build a connection URL without embedding credentials in source code."""
    environment = os.environ if environ is None else environ
    file_values = dotenv_values(env_file)

    def value(name: str, default: str = "") -> str:
        configured = environment[name] if name in environment else file_values.get(name)
        return configured if configured else default

    password = value("WORKSPACE_DB_PASSWORD")
    if not password:
        raise DatabaseConfigurationError("WORKSPACE_DB_PASSWORD must be set.")

    try:
        port = int(value("WORKSPACE_DB_PORT", "5433"))
    except ValueError as exc:
        raise DatabaseConfigurationError("WORKSPACE_DB_PORT must be a valid port.") from exc
    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError("WORKSPACE_DB_PORT must be a valid port.")

    return URL.create(
        "postgresql+psycopg",
        username=value("WORKSPACE_DB_USER", "research_workspace"),
        password=password,
        host=value("WORKSPACE_DB_HOST", "127.0.0.1"),
        port=port,
        database=value("WORKSPACE_DB_NAME", "research_workspace"),
    )


def create_workspace_engine() -> Engine:
    """Create the configured PostgreSQL engine without opening a connection."""
    return create_engine(
        database_url(),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


class WorkspaceDatabase:
    """Create a connection pool on first use and close it at shutdown."""

    def __init__(self, engine_factory: Callable[[], Engine] | None = None) -> None:
        self._engine: Engine | None = None
        self._engine_factory = engine_factory if engine_factory is not None else create_workspace_engine
        self._lock = Lock()

    def _get_engine(self) -> Engine:
        with self._lock:
            if self._engine is None:
                self._engine = self._engine_factory()
            return self._engine

    def check(self) -> None:
        engine = self._get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            if engine.dialect.name == 'postgresql':
                try:
                    revisions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
                except SQLAlchemyError:
                    raise DatabaseConfigurationError('Apply workspace database migrations before starting the workspace.') from None
                if revisions != [SCHEMA_REVISION]:
                    raise DatabaseConfigurationError('Apply workspace database migrations before starting the workspace.')

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit successful work or roll it back before closing the session."""
        with Session(self._get_engine()) as session:
            with session.begin():
                yield session

    def close(self) -> None:
        with self._lock:
            engine, self._engine = self._engine, None
        if engine is not None:
            engine.dispose()
