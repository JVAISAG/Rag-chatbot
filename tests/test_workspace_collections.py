"""Private collection behavior through the workspace API."""

import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from src.workspace.auth.cookies import SESSION_COOKIE
from src.workspace.auth.sessions import issue_session
from src.workspace.auth.settings import AuthSettings
from src.workspace.database import WorkspaceDatabase
from src.workspace.library import routes
from src.workspace.main import create_app
from src.workspace.models import Base, Collection, User
from src.workspace.jobs.worker import Worker
from src.workspace.library.imports import extraction_handler


ORIGIN = {"origin": "http://localhost:3000"}


@pytest.fixture
def collection_api():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    first_user, second_user = uuid.uuid4(), uuid.uuid4()
    with database.transaction() as session:
        session.add_all([User(id=first_user, password_hash="example"), User(id=second_user, password_hash="example")])
    first_token = issue_session(database, first_user).token
    second_token = issue_session(database, second_user).token
    app = create_app(lambda: database, lambda: AuthSettings(cookie_secure=False))
    with TestClient(app, base_url="http://localhost:8001", headers=ORIGIN) as client:
        yield client, database, first_token, second_token


def use_session(client, token):
    client.cookies.clear()
    if token is not None:
        client.cookies.set(SESSION_COOKIE, token)


def test_uploaded_document_is_private_deduplicated_and_readable(collection_api, tmp_path):
    client, database, first, second = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post("/api/v2/collections", json={"name": "Reading"}).json()["id"]
    endpoint = f"/api/v2/collections/{collection}/sources/upload"
    result = client.post(endpoint, files={"file": ("../paper.txt", b"A document about machine learning.")})
    assert result.status_code == 202
    source_id = result.json()["id"]
    assert client.get(f"/api/v2/sources/{source_id}/text").status_code == 409
    again = client.post(endpoint, files={"file": ("other.txt", b"A document about machine learning.")})
    assert again.json()["id"] == source_id
    assert len(list(tmp_path.iterdir())) == 1
    assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
    assert client.get(f"/api/v2/sources/{source_id}/text").json()["pages"][0]["text"] == "A document about machine learning."
    assert client.get(f"/api/v2/collections/{collection}/sources").json()[0]["status"] == "indexing"
    use_session(client, second)
    assert client.get(f"/api/v2/sources/{source_id}/text").status_code == 404
    assert client.get(f"/api/v2/collections/{collection}/sources").status_code == 404
    assert client.post(endpoint, files={"file": ("x.txt", b"secret")}).status_code == 404
    assert len(list(tmp_path.iterdir())) == 1


def test_invalid_documents_fail_without_becoming_readable(collection_api, tmp_path):
    client, database, first, _ = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post("/api/v2/collections", json={"name": "Reading"}).json()["id"]
    endpoint = f"/api/v2/collections/{collection}/sources/upload"
    assert client.post(endpoint, files={"file": ("bad.exe", b"unsupported")}).status_code == 422
    assert client.post(endpoint, files={"file": ("empty.txt", b"")}).status_code == 422
    assert client.post(endpoint, files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1))}).status_code == 413
    assert client.post(endpoint, files={"file": ("safe.txt", b"text")}, headers={"origin": "http://evil.example"}).status_code == 403
    result = client.post(endpoint, files={"file": ("bad.pdf", b"not a PDF")})
    assert result.status_code == 202
    assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
    assert client.get(f"/api/v2/collections/{collection}/sources").json()[0]["status"] == "failed"
    assert client.get(f"/api/v2/sources/{result.json()['id']}/text").status_code == 409


def test_stale_extraction_cannot_publish(collection_api, tmp_path, monkeypatch):
    from datetime import timedelta
    from unittest.mock import MagicMock
    from src.workspace.jobs.queue import claim_job
    from src.workspace.jobs.worker import LeaseLost
    from src.workspace.library import imports
    from src.workspace.models import Job
    client, database, first, _ = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post("/api/v2/collections", json={"name": "Reading"}).json()["id"]
    result = client.post(f"/api/v2/collections/{collection}/sources/upload", files={"file": ("paper.txt", b"Evidence")})
    claimed = claim_job(database, kinds=("extract",), lease=timedelta(minutes=1))
    def parse(*args, **kwargs):
        with database.transaction() as session:
            session.get(Job, claimed.id).lease_token = uuid.uuid4()
        return [{"text": "Evidence", "metadata": {}}]
    monkeypatch.setattr(imports, "load_document", parse)
    with pytest.raises(LeaseLost):
        extraction_handler(database, tmp_path)(claimed, MagicMock())
    assert client.get(f"/api/v2/sources/{result.json()['id']}/text").status_code == 409


@pytest.mark.parametrize("valid", [True, False])
def test_indexing_publishes_all_chunks_or_none(collection_api, tmp_path, valid):
    from src.workspace.library.indexing import indexing_handler, enqueue_missing_indexes
    from src.workspace.models import Chunk, Job, SourceRevision
    client, database, first, second = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post("/api/v2/collections", json={"name": "Index"}).json()["id"]
    assert client.post(f"/api/v2/collections/{collection}/sources/upload", files={"file": ("paper.txt", b"Research evidence.")}).status_code == 202
    Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
    enqueue_missing_indexes(database)
    enqueue_missing_indexes(database)
    with database.transaction() as session:
        assert len(session.scalars(select(Job).where(Job.kind == "index")).all()) == 1
    split = lambda docs: [{"text": docs[0]["text"], "metadata": {"page": 1}}]
    embed = lambda texts: [[1.0] + [0.0] * (383 if valid else 2) for text in texts]
    assert Worker(database, {"index": indexing_handler(database, embed=embed, split=split)}).run_once()
    with database.transaction() as session:
        chunks = session.scalars(select(Chunk)).all()
        revision = session.scalar(select(SourceRevision))
        assert len(chunks) == int(valid)
        assert bool(revision.embedding_model) == valid
    state = client.get(f"/api/v2/collections/{collection}/sources").json()[0]["status"]
    assert state == ("ready" if valid else "indexing_failed")
    if not valid:
        source_id = client.get(f"/api/v2/collections/{collection}/sources").json()[0]["id"]
        assert client.post(f"/api/v2/sources/{source_id}/retry-index").status_code == 202
        assert Worker(database, {"index": indexing_handler(database, embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts], split=split)}).run_once()
        assert client.get(f"/api/v2/collections/{collection}/sources").json()[0]["status"] == "ready"
    use_session(client, second)
    assert client.post(f"/api/v2/collections/{collection}/search", json={"query": "evidence"}).status_code == 404


def test_owner_can_create_read_update_and_delete_a_collection(collection_api):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    created = client.post("/api/v2/collections", json={"name": "  Machine learning  ", "description": " Papers to revisit "})
    assert created.status_code == 201
    data = created.json()
    assert set(data) == {"id", "name", "description", "created_at", "updated_at"}
    assert data["name"] == "Machine learning"
    assert data["description"] == "Papers to revisit"
    assert created.headers["cache-control"] == "no-store"
    path = f"/api/v2/collections/{data['id']}"

    assert client.get("/api/v2/collections").json() == [data]
    assert client.get(path).json() == data
    updated = client.patch(path, json={"name": "Reading list", "description": None})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Reading list"
    assert updated.json()["description"] is None
    assert updated.json()["created_at"] == data["created_at"]
    deleted = client.delete(path)
    assert deleted.status_code == 204 and deleted.content == b""
    assert client.get(path).status_code == 404
    assert client.get("/api/v2/collections").json() == []


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v2/collections"),
    ("POST", "/api/v2/collections"),
    ("GET", f"/api/v2/collections/{uuid.uuid4()}"),
    ("PATCH", f"/api/v2/collections/{uuid.uuid4()}"),
    ("DELETE", f"/api/v2/collections/{uuid.uuid4()}"),
])
def test_every_collection_operation_requires_a_session(collection_api, method, path):
    client, _, _, _ = collection_api
    response = client.request(method, path, json={"name": "Research"})
    assert response.status_code == 401


def test_users_cannot_read_change_delete_or_claim_another_users_collection(collection_api):
    client, _, first_token, second_token = collection_api
    use_session(client, first_token)
    first = client.post("/api/v2/collections", json={"name": "Private", "description": "First account"}).json()
    path = f"/api/v2/collections/{first['id']}"

    use_session(client, second_token)
    assert client.get("/api/v2/collections").json() == []
    assert client.get(path).status_code == 404
    assert client.patch(path, json={"name": "Stolen"}).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.post("/api/v2/collections", json={"name": "Other", "owner_id": str(uuid.uuid4())}).status_code == 422
    own = client.post("/api/v2/collections", json={"name": "Private"})
    assert own.status_code == 201
    assert own.json()["description"] is None
    assert [row["id"] for row in client.get("/api/v2/collections").json()] == [own.json()["id"]]

    use_session(client, first_token)
    assert client.get(path).json() == first


@pytest.mark.parametrize("first,duplicate", [
    ("Reading", "reading"),
    ("Café", "CAFE\u0301"),
    ("Straße", "STRASSE"),
])
def test_names_are_unique_per_owner_without_case_or_unicode_form_differences(collection_api, first, duplicate):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    assert client.post("/api/v2/collections", json={"name": first}).status_code == 201
    response = client.post("/api/v2/collections", json={"name": duplicate})
    assert response.status_code == 409
    assert response.json() == {"detail": "A collection with that name already exists."}


def test_duplicate_rename_does_not_save_any_other_changes(collection_api):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    client.post("/api/v2/collections", json={"name": "Alpha"})
    second = client.post("/api/v2/collections", json={"name": "Beta", "description": "Before"}).json()
    path = f"/api/v2/collections/{second['id']}"
    assert client.patch(path, json={"name": "ALPHA", "description": "Should roll back"}).status_code == 409
    assert client.get(path).json() == second


@pytest.mark.parametrize("payload", [
    {},
    {"name": "  "},
    {"name": None},
    {"name": "x" * 101},
    {"name": "valid", "description": "x" * 2001},
    {"name": "valid", "description": "bad\u0000text"},
    {"name": "valid", "extra": "not allowed"},
])
def test_invalid_collection_input_is_rejected(collection_api, payload):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    assert client.post("/api/v2/collections", json=payload).status_code == 422
    assert client.get("/api/v2/collections").json() == []


def test_empty_update_and_null_name_are_rejected_but_blank_description_clears_it(collection_api):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    created = client.post("/api/v2/collections", json={"name": "Notes", "description": "Draft"}).json()
    path = f"/api/v2/collections/{created['id']}"
    assert client.patch(path, json={}).status_code == 422
    assert client.patch(path, json={"name": None}).status_code == 422
    assert client.patch(path, json={"description": "   "}).json()["description"] is None


def test_mutations_reject_untrusted_origin(collection_api):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)
    created = client.post("/api/v2/collections", json={"name": "Private"}).json()
    path = f"/api/v2/collections/{created['id']}"
    hostile = {"origin": "http://evil.example"}
    assert client.post("/api/v2/collections", json={"name": "Other"}, headers=hostile).status_code == 403
    assert client.patch(path, json={"name": "Changed"}, headers=hostile).status_code == 403
    assert client.delete(path, headers=hostile).status_code == 403
    assert client.get(path).json() == created


def test_database_errors_are_sanitized(collection_api, monkeypatch, caplog):
    client, _, first_token, _ = collection_api
    use_session(client, first_token)

    def fail(*_):
        raise SQLAlchemyError("private database details")

    monkeypatch.setattr(routes, "list_collections", fail)
    response = client.get("/api/v2/collections")
    assert response.status_code == 503
    assert "private database details" not in response.text + caplog.text


def test_deleting_an_account_cascades_its_collections(collection_api):
    client, database, first_token, _ = collection_api
    use_session(client, first_token)
    created = client.post("/api/v2/collections", json={"name": "Notes"}).json()
    with database.transaction() as session:
        collection = session.get(Collection, uuid.UUID(created["id"]))
        owner_id = collection.owner_id
        session.delete(session.get(User, owner_id))
    with database.transaction() as session:
        assert session.scalars(select(Collection).where(Collection.owner_id == owner_id)).all() == []
