from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from test_workspace_collections import collection_api, use_session
from src.workspace import status


def test_heartbeat_expiry_and_status_owner_scope(collection_api, tmp_path, monkeypatch):
    path = tmp_path / 'worker.json'
    monkeypatch.setattr(status, 'HEARTBEAT', path)
    assert not status.worker_available()
    status.record_heartbeat()
    assert status.worker_available()
    with monkeypatch.context() as different:
        different.setenv('WORKSPACE_DB_NAME', 'a_different_workspace')
        assert not status.worker_available()
    path.write_text(json.dumps({'at': (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()}))
    assert not status.worker_available()
    model_client = SimpleNamespace(list=lambda: SimpleNamespace(models=[SimpleNamespace(model='llama3.2:latest')]), close=lambda: None)
    monkeypatch.setattr(status, 'create_client', lambda **kwargs: model_client)
    monkeypatch.setenv('OLLAMA_MODEL', 'llama3.2')
    client, _, first, _ = collection_api
    use_session(client, None)
    assert client.get('/api/v2/status').status_code == 401
    use_session(client, first)
    result = client.get('/api/v2/status')
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    assert result.json()['model_available'] and result.json()['jobs'] == {}
    assert 'X-Request-ID' in result.headers
