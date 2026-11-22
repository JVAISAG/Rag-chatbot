"""Check the workspace in a temporary local database without modifying its library."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from src.workspace.database import WorkspaceDatabase, database_url


def browser(url, *, grep=None):
    """Run every browser test against a disposable database and real API."""
    import socket
    from time import monotonic, sleep
    import requests
    from alembic import command
    from alembic.config import Config

    manifest = json.loads((ROOT / 'frontend/.next/routes-manifest.json').read_text(encoding='utf-8'))
    rewrites = manifest.get('rewrites', {})
    routes = rewrites if isinstance(rewrites, list) else [route for group in rewrites.values() for route in group]
    proxy = [route for route in routes if route.get('source') == '/api/v2/:path*']
    if len(proxy) != 1 or proxy[0].get('destination') != 'http://127.0.0.1:8001/api/v2/:path*':
        raise RuntimeError('Build the frontend with its default local API URL before isolated browser verification.')
    for port in (3000, 8001):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is occupied. Stop the workspace servers before browser verification.')
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / 'workspace.alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
    finally:
        engine.dispose()
    environment = dict(os.environ, WORKSPACE_DB_NAME=url.database, WORKSPACE_COOKIE_SECURE='false', PLAYWRIGHT_HTML_OPEN='never')
    environment.pop('WORKSPACE_E2E_URL', None)
    if os.name == 'nt' and not environment.get('PLAYWRIGHT_BROWSER_EXECUTABLE'):
        edge = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        if edge.is_file():
            environment['PLAYWRIGHT_BROWSER_EXECUTABLE'] = str(edge)
    processes = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    temporary = ROOT / '.cache' / ('browser-check-' + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    print(f'Browser server logs: {temporary}', flush=True)
    with (Path(temporary) / 'api.log').open('w') as api_log, (Path(temporary) / 'frontend.log').open('w') as front_log:
        try:
            processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'src.workspace.main:app',
                '--host', '127.0.0.1', '--port', '8001', '--no-proxy-headers'], cwd=ROOT,
                env=environment, stdout=api_log, stderr=subprocess.STDOUT, creationflags=flags))
            processes.append(subprocess.Popen(['node', str(ROOT / 'frontend/node_modules/next/dist/bin/next'),
                'start', '--hostname', '127.0.0.1', '--port', '3000'], cwd=ROOT / 'frontend',
                env=environment, stdout=front_log, stderr=subprocess.STDOUT, creationflags=flags))
            for address in ('http://127.0.0.1:8001/api/v2/ready', 'http://127.0.0.1:3000/'):
                deadline = monotonic() + 90
                while True:
                    if any(process.poll() is not None for process in processes):
                        raise RuntimeError('A browser verification server stopped unexpectedly.')
                    try:
                        if requests.get(address, timeout=3).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    if monotonic() >= deadline:
                        raise RuntimeError('Browser verification servers did not become ready.')
                    sleep(1)
            print('Running browser checks against an isolated real API/database...', flush=True)
            arguments = ['node', str(ROOT / 'frontend/node_modules/@playwright/test/cli.js'), 'test', '--reporter=line']
            if grep:
                arguments += ['--grep', grep]
            runner = subprocess.Popen(arguments,
                cwd=ROOT / 'frontend', env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace', creationflags=flags)
            processes.append(runner)
            for line in runner.stdout:
                print(line, end='', flush=True)
            if runner.wait() != 0:
                raise RuntimeError('Browser verification failed. Inspect frontend/test-results for the failing test.')
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def live(url):
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from src.workspace.auth.settings import AuthSettings
    from src.workspace.jobs.worker import Worker
    from src.workspace.library.imports import extraction_handler
    from src.workspace.library.indexing import indexing_handler
    from src.workspace.library.questions import answer_handler
    from src.workspace.main import create_app

    engine = create_engine(url, poolclass=NullPool)
    db = WorkspaceDatabase(engine_factory=lambda: engine)
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / 'workspace.alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        with TemporaryDirectory(prefix='live-sources-', dir=ROOT / '.cache') as temporary:
            storage = Path(temporary).resolve()
            if not storage.is_relative_to((ROOT / '.cache').resolve()):
                raise RuntimeError('Unexpected temporary storage path.')
            app = create_app(lambda: db, lambda: AuthSettings(cookie_secure=False))
            app.state.source_storage = storage
            worker = Worker(db, {'extract': extraction_handler(db, storage), 'index': indexing_handler(db), 'answer': answer_handler(db)})
            with TestClient(app, base_url='http://localhost:8001', headers={'Origin': 'http://localhost:3000'}) as client:
                def post(path, payload, expected):
                    result = client.post('/api/v2' + path, json=payload)
                    assert result.status_code == expected, (path, result.status_code, result.text)
                    return result.json() if result.content else None
                username = 'live_' + uuid.uuid4().hex[:12]
                password = 'synthetic-test-password'
                post('/auth/register', {'username': username, 'password': password}, 201)
                post('/auth/login', {'identifier': username, 'password': password}, 200)
                collection = post('/collections', {'name': 'Synthetic study'}, 201)['id']
                text = b'The synthetic test study trained a classifier with a batch size of 64 for 16 epochs.'
                response = client.post(f'/api/v2/collections/{collection}/sources/upload', files={'file': ('synthetic-study.txt', text)})
                assert response.status_code == 202, response.text
                source = response.json()['id']
                print('Extracting and indexing with the real embedding model...', flush=True)
                assert worker.run_once()
                assert worker.run_once()
                sources = client.get(f'/api/v2/collections/{collection}/sources').json()
                assert sources[0]['status'] == 'ready', sources
                hits = post(f'/collections/{collection}/search', {'query': 'What batch size and training epochs did the study use?'}, 200)
                assert hits and hits[0]['metadata']['source_id'] == source, hits
                print('Real BM25, pgvector search, and cross-encoder returned the study.', flush=True)
                conversation = post(f'/collections/{collection}/conversations', None, 201)['id']
                for question, numbers in [('What batch size and how many training epochs did the study use?', ['64', '16']), ('How many epochs did it use?', ['16'])]:
                    post(f'/conversations/{conversation}/messages', {'question': question}, 202)
                    assert worker.run_once()
                    turns = client.get(f'/api/v2/conversations/{conversation}').json()['turns']
                    turn = turns[-1]
                    assert turn['status'] == 'completed', turn
                    assert all(number in turn['answer'] for number in numbers), turn
                    assert turn['evidence'] and turn['evidence'][0]['available'], turn
                    assert turn['evidence'][0]['metadata']['source_id'] == source, turn
                    print(json.dumps({'question': question, 'answer': turn['answer'], 'references': len(turn['evidence'])}), flush=True)
                empty = post('/collections', {'name': 'Empty study'}, 201)['id']
                empty_conversation = post(f'/collections/{empty}/conversations', None, 201)['id']
                post(f'/conversations/{empty_conversation}/messages', {'question': 'What settings were used?'}, 202)
                assert worker.run_once()
                assert client.get(f'/api/v2/conversations/{empty_conversation}').json()['turns'][0]['status'] == 'no_evidence'
                post('/auth/logout', None, 204)
                other = 'other_' + uuid.uuid4().hex[:12]
                post('/auth/register', {'username': other, 'password': password}, 201)
                post('/auth/login', {'identifier': other, 'password': password}, 200)
                for path in [f'/collections/{collection}', f'/conversations/{conversation}', f'/sources/{source}/text']:
                    assert client.get('/api/v2' + path).status_code == 404, path
                print('PASS: real upload, extraction, indexing, hybrid search, cited answers, follow-up, empty scope, and account isolation.', flush=True)
    finally:
        db.close()
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['integration', 'browser', 'live', 'evaluation'], help='Run database/browser tests, a live pipeline, or the synthetic retrieval benchmark.')
    parser.add_argument('--report', type=Path, default=ROOT / '.cache/workspace-evaluation.json')
    parser.add_argument('--answers', action='store_true', help='Also save real-model answers for semantic review (evaluation mode).')
    parser.add_argument('--answers-only', action='store_true', help='Save real-model answers without repeating the four retrieval ablations (evaluation mode).')
    parser.add_argument('--browser-grep', help='Run matching browser test titles only (browser mode).')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'eval/workspace_set.json', help='Evaluation corpus, validated before creating any test database.')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Run without Python optimization so verification assertions remain active.')
    load_dotenv(ROOT / '.env', override=False)
    mode = args.mode
    if mode == 'evaluation':
        from eval.workspace_dataset import load_dataset
        try:
            load_dataset(args.dataset)
        except (OSError, ValueError, TypeError) as exc:
            parser.error(f'Invalid evaluation dataset: {type(exc).__name__}.')
    base = database_url()
    if base.host not in {'localhost', '127.0.0.1'}:
        parser.error('Verification requires a local workspace PostgreSQL server.')
    if mode == 'live' or (mode == 'evaluation' and (args.answers or args.answers_only)):
        from urllib.parse import urlsplit
        host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        if urlsplit(host if '://' in host else 'http://' + host).hostname not in {'localhost', '127.0.0.1', '::1'}:
            parser.error('Live verification requires a local Ollama server.')
    name = 'research_test_' + uuid.uuid4().hex[:12]
    if not re.fullmatch(r'research_test_[0-9a-f]{12}', name) or name == base.database:
        raise RuntimeError('Unexpected temporary database name.')
    admin = create_engine(base, isolation_level='AUTOCOMMIT', poolclass=NullPool)
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        if mode == 'integration':
            environment = dict(os.environ, WORKSPACE_DB_NAME=name, WORKSPACE_RUN_POSTGRES_TESTS='1')
            files = ['tests/test_workspace_migrations.py'] + [str(p.relative_to(ROOT)) for p in sorted((ROOT / 'tests').glob('test_workspace_*_postgres.py'))]
            subprocess.run([sys.executable, '-m', 'pytest', '-q', '--tb=short', *files], cwd=ROOT, env=environment, check=True)
        elif mode == 'browser':
            browser(base.set(database=name), grep=args.browser_grep)
        elif mode == 'evaluation':
            os.environ['HF_HUB_OFFLINE'] = '1'
            from eval.workspace import evaluate
            evaluate(base.set(database=name), args.report, generate_answers=args.answers or args.answers_only,
                score_retrieval=not args.answers_only, dataset_path=args.dataset)
        else:
            os.environ['HF_HUB_OFFLINE'] = '1'
            live(base.set(database=name))
    finally:
        try:
            if created:
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
                print('Removed isolated verification database.', flush=True)
        finally:
            admin.dispose()


if __name__ == '__main__':
    main()
