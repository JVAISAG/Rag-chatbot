"""Migration checks; PostgreSQL integration is explicitly opt-in."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, delete, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from src.workspace.database import SCHEMA_REVISION, database_url
from src.workspace.models import Collection, Job, Source, User, UserIdentifier, UserSession


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = PROJECT_ROOT / "workspace.alembic.ini"


def test_workspace_has_one_linear_migration_head():
    scripts = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))

    assert scripts.get_heads() == ["20261121_01"]
    assert scripts.get_heads() == [SCHEMA_REVISION]
    assert scripts.get_revision("20261121_01").down_revision == "20261120_01"
    assert scripts.get_revision("20261120_01").down_revision == "20261115_06"
    assert scripts.get_revision("20261115_06").down_revision == "20261115_05"
    assert scripts.get_revision("20261115_05").down_revision == "20261115_04"
    assert scripts.get_revision("20261115_04").down_revision == "20261115_03"
    assert scripts.get_revision("20261115_03").down_revision == "20261115_02"
    assert scripts.get_revision("20261115_02").down_revision == "20261115_01"
    assert scripts.get_revision("20261115_01").down_revision == "20261114_01"
    assert scripts.get_revision("20261114_01").down_revision == "20261113_01"
    assert scripts.get_revision("20261113_01").down_revision == "20261110_02"
    assert scripts.get_revision("20261110_02").down_revision == "20261110_01"
    assert scripts.get_revision("20261110_01").down_revision == "20261108_02"
    assert scripts.get_revision("20261108_02").down_revision == "20261108_01"
    assert scripts.get_revision("20261108_01").down_revision == "20261107_02"
    assert scripts.get_revision("20261107_02").down_revision == "20261107_01"


@pytest.mark.skipif(os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1", reason="Requires isolated PostgreSQL.")
def test_metadata_migration_preserves_existing_sources():
    engine = create_engine(database_url(), poolclass=NullPool, connect_args={"connect_timeout": 3})
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"workspace_test_{uuid.uuid4().hex}"
    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        config = Config(str(ALEMBIC_CONFIG))
        config.attributes["connection"] = connection
        command.upgrade(config, "20261114_01")
        user_id, job_id, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        connection.execute(insert(User), {"id": user_id, "password_hash": "example"})
        connection.execute(insert(Job), {"id": job_id, "owner_id": user_id, "kind": "extract", "payload": {}})
        connection.execute(text("INSERT INTO sources (id, owner_id, filename, content_hash, storage_key, job_id) VALUES (:id, :owner, :filename, :hash, :key, :job)"),
                           {"id": source_id, "owner": user_id, "filename": "old.txt", "hash": "a" * 64, "key": "old.txt", "job": job_id})
        command.upgrade(config, "head")
        row = connection.execute(select(Source.filename, Source.title, Source.authors, Source.publication_date, Source.tags, Source.reading_status).where(Source.id == source_id)).one()
        assert tuple(row) == ("old.txt", None, None, None, [], 'unread')
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(text("UPDATE sources SET reading_status = 'finished'"))
        connection.execute(text("UPDATE sources SET tags = '[\"ML\"]', reading_status = 'read'"))
        with pytest.raises(RuntimeError, match='saved source tags'):
            command.downgrade(config, '20261120_01')
        connection.execute(text("UPDATE sources SET tags = '[]', reading_status = 'unread'"))
        command.downgrade(config, '20261120_01')
        command.upgrade(config, 'head')
        assert connection.execute(select(Source.filename, Source.tags, Source.reading_status)).one() == ('old.txt', [], 'unread')
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.mark.skipif(os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1", reason="Requires isolated PostgreSQL.")
def test_revision_migration_preserves_ready_and_pending_documents():
    engine = create_engine(database_url(), poolclass=NullPool, connect_args={"connect_timeout": 3})
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"workspace_test_{uuid.uuid4().hex}"
    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        config = Config(str(ALEMBIC_CONFIG))
        config.attributes["connection"] = connection
        command.upgrade(config, "20261115_01")
        owner = uuid.uuid4()
        connection.execute(insert(User), {"id": owner, "password_hash": "example"})
        source_ids, revision_ids = [], []
        for number, model in enumerate(("all-MiniLM-L6-v2", None)):
            job_id, source_id, revision_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            source_ids.append(source_id)
            revision_ids.append(revision_id)
            connection.execute(insert(Job), {"id": job_id, "owner_id": owner, "kind": "extract", "payload": {}})
            connection.execute(text("INSERT INTO sources (id, owner_id, filename, content_hash, storage_key, job_id) VALUES (:id, :owner, :filename, :hash, :key, :job)"),
                {"id": source_id, "owner": owner, "filename": f"{number}.txt", "hash": str(number) * 64, "key": f"{number}.txt", "job": job_id})
            connection.execute(text("INSERT INTO source_revisions (id, source_id, pages, extraction_version, embedding_model) VALUES (:id, :source, '[]', 'loader-v1', :model)"),
                {"id": revision_id, "source": source_id, "model": model})
        command.upgrade(config, "head")
        assert connection.scalar(select(Source.active_revision_id).where(Source.id == source_ids[0])) == revision_ids[0]
        assert connection.scalar(select(Source.active_revision_id).where(Source.id == source_ids[1])) is None
        assert connection.scalar(text("SELECT count(*) FROM source_revisions")) == 2
        revision_file = connection.execute(text("SELECT filename, storage_key, content_hash FROM source_revisions WHERE id = :id"), {"id": revision_ids[0]}).one()
        assert tuple(revision_file) == ("0.txt", "0.txt", "0" * 64)
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.mark.skipif(
    os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1",
    reason="Set WORKSPACE_RUN_POSTGRES_TESTS=1 for isolated PostgreSQL migration tests.",
)
def test_migrations_and_account_constraints_in_postgres():
    engine = create_engine(database_url(), poolclass=NullPool, connect_args={"connect_timeout": 3})
    connection = engine.connect()
    transaction = connection.begin()
    schema = f"workspace_test_{uuid.uuid4().hex}"

    try:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}", public')
        config = Config(str(ALEMBIC_CONFIG))
        config.attributes["connection"] = connection

        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261121_01"
        assert connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
        assert transaction.is_active

        email_user, username_user = uuid.uuid4(), uuid.uuid4()
        connection.execute(
            insert(User),
            [{"id": email_user, "password_hash": "example-hash"},
             {"id": username_user, "password_hash": "example-hash"}],
        )
        connection.execute(
            insert(UserIdentifier),
            [
                {"user_id": email_user, "kind": "email", "value": "Author@example.com",
                 "normalized_value": "author@example.com"},
                {"user_id": username_user, "kind": "username", "value": "Reader",
                 "normalized_value": "reader"},
                {"user_id": email_user, "kind": "username", "value": "Author",
                 "normalized_value": "author"},
            ],
        )

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(UserIdentifier), {
                "user_id": username_user, "kind": "email", "value": "reader",
                "normalized_value": "reader",
            })
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(UserIdentifier), {
                "user_id": email_user, "kind": "email", "value": "another@example.com",
                "normalized_value": "another@example.com",
            })

        session_id = uuid.uuid4()
        connection.execute(insert(UserSession), {
            "id": session_id, "user_id": email_user, "token_hash": "example-token-hash",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        first_collection, second_collection = uuid.uuid4(), uuid.uuid4()
        connection.execute(insert(Collection), [
            {"id": first_collection, "owner_id": email_user, "name": "Papers", "normalized_name": "papers"},
            {"id": second_collection, "owner_id": username_user, "name": "Papers", "normalized_name": "papers"},
        ])
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(insert(Collection), {
                "id": uuid.uuid4(), "owner_id": email_user, "name": "PAPERS", "normalized_name": "papers",
            })
        connection.execute(delete(User).where(User.id == email_user))
        assert connection.scalar(select(UserSession.id).where(UserSession.id == session_id)) is None
        assert connection.scalar(select(UserIdentifier.id).where(UserIdentifier.user_id == email_user)) is None
        assert connection.scalar(select(Collection.id).where(Collection.id == first_collection)) is None
        assert connection.scalar(select(Collection.id).where(Collection.id == second_collection)) == second_collection

        command.downgrade(config, "base")
        assert connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"{schema}.users"}) is None
        assert connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
        assert transaction.is_active
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
