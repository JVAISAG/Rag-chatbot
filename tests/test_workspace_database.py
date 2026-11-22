"""Configuration checks for the workspace database connection."""

from unittest.mock import MagicMock
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from src.workspace.database import SCHEMA_REVISION, DatabaseConfigurationError, WorkspaceDatabase, database_url
from src.workspace.models import Base, User, UserIdentifier


def test_database_url_uses_compose_defaults_and_keeps_password_private(tmp_path):
    password = "secret:@/word"
    url = database_url({"WORKSPACE_DB_PASSWORD": password}, tmp_path / ".env")

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "127.0.0.1"
    assert url.port == 5433
    assert url.username == "research_workspace"
    assert url.database == "research_workspace"
    assert url.password == password
    assert password not in str(url)


def test_database_url_reads_dotenv_and_prefers_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "WORKSPACE_DB_PASSWORD=local-password\n"
        "WORKSPACE_DB_USER=from-file\n"
        "WORKSPACE_DB_NAME=local-db\n"
        "WORKSPACE_DB_PORT=55432\n",
        encoding="utf-8",
    )
    url = database_url({"WORKSPACE_DB_USER": "from-environment"}, env_file)

    assert url.username == "from-environment"
    assert url.database == "local-db"
    assert url.port == 55432
    assert url.password == "local-password"


def test_database_url_requires_password(tmp_path):
    with pytest.raises(DatabaseConfigurationError, match="WORKSPACE_DB_PASSWORD"):
        database_url({}, tmp_path / ".env")


@pytest.mark.parametrize("port", ["0", "65536", "-1", "invalid"])
def test_database_url_rejects_invalid_port(tmp_path, port):
    environment = {"WORKSPACE_DB_PASSWORD": "secret", "WORKSPACE_DB_PORT": port}
    with pytest.raises(DatabaseConfigurationError, match="WORKSPACE_DB_PORT"):
        database_url(environment, tmp_path / ".env")


def test_transaction_commits_success_and_rolls_back_partial_registration():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    engine_factory = MagicMock(return_value=engine)
    database = WorkspaceDatabase(engine_factory=engine_factory)
    existing_id, rejected_id = uuid.uuid4(), uuid.uuid4()

    try:
        engine_factory.assert_not_called()
        database.check()
        with database.transaction() as session:
            session.add(User(id=existing_id, password_hash="example-hash"))
            session.flush()
            session.add(UserIdentifier(
                user_id=existing_id, kind="username", value="Reader", normalized_value="reader",
            ))

        with pytest.raises(IntegrityError):
            with database.transaction() as session:
                session.add(User(id=rejected_id, password_hash="example-hash"))
                session.flush()
                session.add(UserIdentifier(
                    user_id=rejected_id, kind="username", value="reader", normalized_value="reader",
                ))

        with database.transaction() as session:
            assert session.get(User, existing_id) is not None
            assert session.get(User, rejected_id) is None
            identifiers = session.scalars(select(UserIdentifier)).all()
            assert len(identifiers) == 1
            assert identifiers[0].user_id == existing_id

        engine_factory.assert_called_once_with()
    finally:
        database.close()


@pytest.mark.parametrize('revisions', [[], ['20261120_01'], ['unexpected-head'], [SCHEMA_REVISION, 'another-head']])
def test_postgres_readiness_rejects_missing_or_incompatible_schema(revisions):
    engine = MagicMock()
    engine.dialect.name = 'postgresql'
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value.all.return_value = revisions
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    with pytest.raises(DatabaseConfigurationError, match='migrations'):
        database.check()
    database.close()


def test_postgres_readiness_accepts_current_migration():
    engine = MagicMock()
    engine.dialect.name = 'postgresql'
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalars.return_value.all.return_value = [SCHEMA_REVISION]
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    database.check()
    database.close()
