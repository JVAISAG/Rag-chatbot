from src.generation import client
from unittest.mock import MagicMock
import pytest
from src.errors import ModelUnavailableError


def test_model_settings_use_environment_then_dotenv_then_default(monkeypatch):
    monkeypatch.delenv('OLLAMA_MODEL', raising=False)
    monkeypatch.setattr(client, 'dotenv_values', lambda path: {'OLLAMA_MODEL': 'file-model'})
    assert client.setting('OLLAMA_MODEL', 'default-model') == 'file-model'
    monkeypatch.setenv('OLLAMA_MODEL', 'environment-model')
    assert client.setting('OLLAMA_MODEL', 'default-model') == 'environment-model'
    monkeypatch.setenv('OLLAMA_MODEL', '')
    assert client.setting('OLLAMA_MODEL', 'default-model') == 'default-model'


def test_diagnostic_timeout_overrides_generation_timeout(monkeypatch):
    monkeypatch.setenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
    monkeypatch.setenv('OLLAMA_TIMEOUT', '120')
    captured = {}
    monkeypatch.setattr(client.ollama, 'Client', lambda **options: captured.update(options))
    client.create_client(timeout=3)
    assert captured['timeout'] == 3


def test_prompt_batch_can_reduce_peak_inference_memory(monkeypatch):
    monkeypatch.setenv('OLLAMA_BATCH_SIZE', '64')
    monkeypatch.setenv('OLLAMA_KEEP_ALIVE', '5m')
    model = MagicMock()
    model.generate.return_value = {'response': 'Ready'}
    assert client.generate_text(model, 'test-model', 'Question') == 'Ready'
    assert model.generate.call_args.kwargs['options']['num_batch'] == 64
    assert model.generate.call_args.kwargs['keep_alive'] == '5m'


@pytest.mark.parametrize('batch', ['0', '-1', '513', 'invalid'])
def test_invalid_batches_do_not_reach_the_model(monkeypatch, batch):
    monkeypatch.setenv('OLLAMA_BATCH_SIZE', batch)
    model = MagicMock()
    with pytest.raises(ModelUnavailableError):
        client.generate_text(model, 'test-model', 'Question')
    model.generate.assert_not_called()


def test_gpu_layer_placement_is_optional(monkeypatch):
    monkeypatch.setattr(client, 'dotenv_values', lambda path: {})
    monkeypatch.delenv('OLLAMA_GPU_LAYERS', raising=False)
    model = MagicMock()
    model.generate.return_value = {'response': 'Ready'}
    client.generate_text(model, 'fixture', 'Question')
    assert 'num_gpu' not in model.generate.call_args.kwargs['options']
    monkeypatch.setenv('OLLAMA_GPU_LAYERS', '99')
    client.generate_text(model, 'fixture', 'Question')
    assert model.generate.call_args.kwargs['options']['num_gpu'] == 99


@pytest.mark.parametrize('layers', ['-2', '1000', 'invalid'])
def test_invalid_gpu_layers_do_not_reach_the_model(monkeypatch, layers):
    monkeypatch.setenv('OLLAMA_GPU_LAYERS', layers)
    model = MagicMock()
    with pytest.raises(ModelUnavailableError):
        client.generate_text(model, 'fixture', 'Question')
    model.generate.assert_not_called()


def test_model_prompts_bypass_ambient_http_proxies(monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.received.append(self.rfile.read(int(self.headers['Content-Length'])))
            body = json.dumps({'response': 'Ready', 'done': True}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    endpoints = []
    for _ in range(2):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Endpoint)
        server.received = []
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoints.append((server, thread))
    model_server, proxy = endpoints[0][0], endpoints[1][0]
    model = None
    try:
        monkeypatch.setenv('OLLAMA_HOST', f'http://127.0.0.1:{model_server.server_port}')
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
            monkeypatch.setenv(key, f'http://127.0.0.1:{proxy.server_port}')
        monkeypatch.setenv('NO_PROXY', '')
        monkeypatch.setenv('OLLAMA_BATCH_SIZE', '128')
        model = client.create_client(timeout=3)
        assert client.generate_text(model, 'fixture', 'A private synthetic question') == 'Ready'
        assert len(model_server.received) == 1 and proxy.received == []
    finally:
        if model is not None:
            model.close()
        for server, thread in endpoints:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
