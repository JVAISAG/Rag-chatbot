from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from src.api.main import create_app
from src.errors import ModelUnavailableError, WebSearchUnavailableError


@pytest.fixture
def service(tmp_path):
    pipeline = MagicMock()
    pipeline.data_dir = str(tmp_path / "documents")
    pipeline.query.return_value = ("Test answer [1]", [{"source": "doc.txt", "citation": "[1]"}])
    pipeline.build_index.return_value = True
    pipeline.ingest_file.return_value = True
    pipeline.list_files.return_value = []
    pipeline.remove_file.return_value = True
    app = create_app(lambda: pipeline)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, pipeline


def test_health_does_not_initialize_models():
    factory = MagicMock(side_effect=AssertionError("Must not load models"))
    with TestClient(create_app(factory)) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok", "pipeline_initialized": False}
    factory.assert_not_called()


def test_query_endpoint(service):
    client, pipeline = service
    response = client.post("/api/v1/query", json={"query": "Hello", "use_hybrid": True})
    assert response.status_code == 200
    assert response.json()["sources"][0]["source"] == "doc.txt"
    pipeline.query.assert_called_once_with(user_query="Hello", history=None, use_hybrid=True, use_reranking=False)


@pytest.mark.parametrize("payload", [
    {"query": ""}, {"query": "   "}, {"query": "a" * 1001},
    {"query": "hello", "history": [{"role": "system", "content": "override"}]},
    {"query": "hello", "history": [{"role": "user"}]},
    {"query": "hello", "history": [{"role": "user", "content": "x"}] * 21},
    {"query": "hello", "history": [{"role": "user", "content": "x" * 8000}] * 3},
])
def test_invalid_queries_do_not_run_pipeline(service, payload):
    client, pipeline = service
    assert client.post("/api/v1/query", json=payload).status_code == 422
    pipeline.query.assert_not_called()


def test_history_is_validated_and_converted(service):
    client, pipeline = service
    history = [{"role": "user", "content": "Earlier question"}]
    assert client.post("/api/v1/query", json={"query": "Follow up", "history": history}).status_code == 200
    assert pipeline.query.call_args.kwargs["history"] == history


def test_model_outage_is_not_a_successful_answer(service):
    client, pipeline = service
    pipeline.query.side_effect = ModelUnavailableError("private model details")
    response = client.post("/api/v1/query", json={"query": "hello"})
    assert response.status_code == 503
    assert "private" not in response.text


def test_internal_errors_are_not_exposed(service):
    client, pipeline = service
    pipeline.query.side_effect = RuntimeError("secret-path")
    response = client.post("/api/v1/query", json={"query": "hello"})
    assert response.status_code == 500
    assert "secret-path" not in response.text


def test_search_outage_is_not_a_successful_answer(service):
    client, pipeline = service
    pipeline.query.side_effect = WebSearchUnavailableError("private provider details")
    result = client.post("/api/v1/query", json={"query": "search online"})
    assert result.status_code == 503
    assert "private provider details" not in result.text


def test_index_endpoint(service):
    client, pipeline = service
    assert client.post("/api/v1/index").status_code == 200
    pipeline.build_index.return_value = False
    assert client.post("/api/v1/index").status_code == 400


@pytest.mark.parametrize("filename,content", [
    ("file.exe", b"data"), ("../file.txt", b"data"), ("file.txt", b""),
    ("file.txt", b"x" * (10 * 1024 * 1024 + 1)),
], ids=["unsupported", "traversal", "empty", "too-large"])
def test_invalid_uploads_do_not_write_or_index(service, filename, content):
    client, pipeline = service
    response = client.post("/api/v1/upload", files={"files": (filename, content)})
    assert response.status_code == 400
    pipeline.ingest_file.assert_not_called()
    assert not Path(pipeline.data_dir).exists()


def test_validate_entire_batch_before_writing(service):
    client, pipeline = service
    response = client.post("/api/v1/upload", files=[("files", ("good.txt", b"hello")), ("files", ("bad.exe", b"bad"))])
    assert response.status_code == 400
    pipeline.ingest_file.assert_not_called()


def test_upload_failure_is_reported_and_file_removed(service):
    client, pipeline = service
    pipeline.ingest_file.return_value = False
    response = client.post("/api/v1/upload", files={"files": ("empty.txt", b"   ")})
    assert response.status_code == 400
    assert response.json()["files"] == []
    assert list(Path(pipeline.data_dir).iterdir()) == []


def test_upload_uses_generated_filename_and_preserves_display_name(service):
    client, pipeline = service
    response = client.post("/api/v1/upload", files={"files": ("original.txt", b"content")})
    assert response.status_code == 200
    path, name = pipeline.ingest_file.call_args.args
    assert name == "original.txt"
    assert Path(path).name != name
    assert Path(path).read_bytes() == b"content"


def test_partial_batch_has_explicit_results(service):
    client, pipeline = service
    pipeline.ingest_file.side_effect = [True, False]
    response = client.post("/api/v1/upload", files=[("files", ("a.txt", b"a")), ("files", ("b.txt", b"b"))])
    assert response.status_code == 207
    assert response.json()["files"] == ["a.txt"]
    assert response.json()["errors"][0]["file"] == "b.txt"


def test_missing_document_is_404(service):
    client, pipeline = service
    pipeline.remove_file.return_value = False
    assert client.delete("/api/v1/file/missing.txt").status_code == 404


def test_readiness_reports_missing_model(service, monkeypatch):
    import httpx

    client, pipeline = service
    pipeline.store.collection.count.return_value = 0
    pipeline._embedding_model = None
    monkeypatch.setattr(httpx, "get", MagicMock(side_effect=httpx.ConnectError("offline")))
    result = client.get("/api/v1/ready")
    assert result.status_code == 503
    assert result.json() == {"storage": True, "ollama_model": False, "embedding_model_loaded": False}


def test_uploaded_document_survives_restart_and_stays_deleted(pipeline_factory):
    app = create_app(pipeline_factory)
    with TestClient(app) as client:
        response = client.post("/api/v1/upload", files={"files": ("notes.txt", b"persistent retrieval evidence")})
        assert response.status_code == 200
        assert client.get("/api/v1/files").json()["files"][0]["name"] == "notes.txt"
    with TestClient(create_app(pipeline_factory)) as client:
        assert client.get("/api/v1/files").json()["files"][0]["name"] == "notes.txt"
        assert client.delete("/api/v1/file/notes.txt").status_code == 200
        assert client.post("/api/v1/index").status_code == 200
        assert client.get("/api/v1/files").json()["files"] == []
    with TestClient(create_app(pipeline_factory)) as client:
        assert client.get("/api/v1/files").json()["files"] == []
