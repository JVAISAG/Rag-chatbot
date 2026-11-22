"""Local worker heartbeat and authenticated dependency diagnostics."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from src.generation.client import DEFAULT_MODEL, create_client, setting
from src.workspace.auth.dependencies import require_user
from src.workspace.library.imports import DEFAULT_STORAGE
from src.workspace.library.routes import _collection_errors
from src.workspace.models import Job
from src.workspace.database import DEFAULT_ENV_FILE
from dotenv import dotenv_values

HEARTBEAT = Path(__file__).resolve().parents[2] / '.cache' / 'workspace-worker.json'
router = APIRouter(prefix='/api/v2', tags=['status'])


def database_identity():
    values = dotenv_values(DEFAULT_ENV_FILE)
    return '|'.join(os.getenv(key) or values.get(key) or default for key, default in (
        ('WORKSPACE_DB_HOST', '127.0.0.1'), ('WORKSPACE_DB_PORT', '5433'), ('WORKSPACE_DB_NAME', 'research_workspace')))


def record_heartbeat():
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    temporary = HEARTBEAT.with_name('worker-' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'pid': os.getpid(), 'database': database_identity(), 'at': datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
        temporary.replace(HEARTBEAT)
    finally:
        temporary.unlink(missing_ok=True)


def worker_available():
    try:
        data = json.loads(HEARTBEAT.read_text(encoding='utf-8'))
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(data['at'])).total_seconds()
        return data.get('database') == database_identity() and 0 <= elapsed < 90
    except (OSError, ValueError, KeyError, TypeError):
        return False


@router.get('/status')
def status(request: Request, response: Response, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors():
        request.app.state.database.check()
    with _collection_errors(), request.app.state.database.transaction() as session:
        counts = session.execute(select(Job.status, func.count()).where(Job.owner_id == owner).group_by(Job.status)).all()
    model = setting('OLLAMA_MODEL', DEFAULT_MODEL)
    model_available = False
    client = None
    try:
        client = create_client(timeout=3)
        names = [item.model for item in client.list().models]
        model_available = model in names or model + ':latest' in names
    except Exception:
        pass
    finally:
        if client is not None: client.close()
    root = getattr(request.app.state, 'source_storage', DEFAULT_STORAGE)
    response.headers['Cache-Control'] = 'no-store'
    return {'database': True, 'worker': worker_available(), 'storage': os.access(root if root.exists() else root.parent, os.W_OK),
        'model': model, 'model_available': model_available, 'jobs': dict(counts)}
