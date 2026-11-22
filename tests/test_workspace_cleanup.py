"""Cleanup preserves current and historical evidence while reclaiming staging files."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select
from test_workspace_collections import collection_api
from test_workspace_replacements import prepare
from src.workspace.library.cleanup import reconcile_storage
from src.workspace.models import Source, SourceReplacement


def test_cleanup_preserves_revisions_and_live_staging(collection_api, tmp_path):
    client, database, _, _, _, source_id, _, extract, index = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/sources/{source_id}/replace'
    with database.transaction() as session:
        original_key = session.get(Source, uuid.UUID(source_id)).storage_key
    assert client.post(endpoint, files={'file': ('updated.txt', b'Updated evidence.')}).status_code == 202
    assert extract.run_once() and index.run_once()
    with database.transaction() as session:
        active_key = session.get(Source, uuid.UUID(source_id)).storage_key
    assert client.post(endpoint, files={'file': ('bad.pdf', b'not a pdf')}).status_code == 202
    assert extract.run_once()
    with database.transaction() as session:
        failed_key = session.scalar(select(SourceReplacement.storage_key).where(SourceReplacement.filename == 'bad.pdf'))
    assert client.post(endpoint, files={'file': ('future.txt', b'Future evidence.')}).status_code == 202
    with database.transaction() as session:
        staged_key = session.scalar(select(SourceReplacement.storage_key).where(SourceReplacement.filename == 'future.txt'))

    now = datetime.now(timezone.utc)
    os.utime(tmp_path / staged_key, (now.timestamp() - 90000, now.timestamp() - 90000))
    old_orphan = tmp_path / (uuid.uuid4().hex + '.txt')
    old_orphan.write_text('orphan')
    os.utime(old_orphan, (now.timestamp() - 90000, now.timestamp() - 90000))
    recent_orphan = tmp_path / (uuid.uuid4().hex + '.txt')
    recent_orphan.write_text('recent')
    unrelated = tmp_path / 'notes.txt'
    unrelated.write_text('not managed by staging')
    folder = tmp_path / (uuid.uuid4().hex + '.pdf')
    folder.mkdir()
    link = tmp_path / (uuid.uuid4().hex + '.txt')
    try:
        link.symlink_to(unrelated)
    except OSError:
        link = None  # Creating symbolic links may require Windows privileges.
    assert reconcile_storage(database, tmp_path, now=now) == 2
    assert not (tmp_path / failed_key).exists() and not old_orphan.exists()
    assert all((tmp_path / key).exists() for key in (original_key, active_key, staged_key))
    assert recent_orphan.exists() and unrelated.exists() and folder.is_dir()
    assert link is None or link.is_symlink()
    assert reconcile_storage(database, tmp_path, now=now) == 0
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Updated evidence.'
    assert extract.run_once() and index.run_once()
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Future evidence.'


def test_cleanup_fails_closed_on_database_errors(collection_api, tmp_path):
    class BrokenDatabase:
        def transaction(self):
            raise RuntimeError('database unavailable')
    orphan = tmp_path / (uuid.uuid4().hex + '.txt')
    orphan.write_text('keep')
    old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))
    with pytest.raises(RuntimeError):
        reconcile_storage(BrokenDatabase(), tmp_path)
    assert orphan.exists()


def test_cleanup_retries_filesystem_errors(collection_api, tmp_path, monkeypatch):
    _, database, _, _ = collection_api
    orphan = tmp_path / (uuid.uuid4().hex + '.txt')
    orphan.write_text('orphan')
    old = (datetime.now(timezone.utc) - timedelta(days=2)).timestamp()
    os.utime(orphan, (old, old))
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path == orphan:
            raise PermissionError('locked')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', locked)
    assert reconcile_storage(database, tmp_path) == 0 and orphan.exists()
    monkeypatch.setattr(Path, 'unlink', original)
    assert reconcile_storage(database, tmp_path) == 1 and not orphan.exists()
