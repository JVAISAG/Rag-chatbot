import json
from pathlib import Path
from unittest.mock import MagicMock

import requests
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[1] / "app.py")
# Cold imports can exceed ten seconds on the supported 8 GB development machine.
APP_TIMEOUT = 30


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def test_chat_citations_survive_reruns(monkeypatch):
    get = MagicMock(return_value=response({"files": []}))
    post = MagicMock(return_value=response({
        "answer": "Supported answer [3].",
        "sources": [{"citation": "[3]", "source": "notes.pdf", "metadata": {"source": "notes.pdf", "page": 2}, "text_snippet": "Evidence"}],
    }))
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    app = AppTest.from_file(APP_PATH, default_timeout=APP_TIMEOUT).run()
    assert not app.exception
    app.chat_input[0].set_value("question").run()
    assert not app.exception
    assert any("[3] notes.pdf, page 2" in item.value for item in app.markdown)
    app.run()
    assert any("[3] notes.pdf, page 2" in item.value for item in app.markdown)
    assert post.call_args.kwargs["timeout"][0] == 5


def test_offline_backend_is_an_error_without_crashing(monkeypatch):
    monkeypatch.setattr(requests, "get", MagicMock(side_effect=requests.ConnectionError("offline")))
    app = AppTest.from_file(APP_PATH, default_timeout=APP_TIMEOUT).run()
    assert not app.exception
    assert any("Failed to connect" in item.value for item in app.error)


def test_deletion_is_an_explicit_action(monkeypatch):
    get = MagicMock(side_effect=[response({"files": [{"name": "notes.txt", "chunks": 1}]}), response({"files": [{"name": "notes.txt", "chunks": 1}]}), response({"files": []})])
    delete = MagicMock(return_value=response({"message": "removed"}))
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "delete", delete)
    app = AppTest.from_file(APP_PATH, default_timeout=APP_TIMEOUT).run()
    delete.assert_not_called()
    app.button(key="delete_notes.txt").click().run()
    assert not app.exception
    delete.assert_called_once()
