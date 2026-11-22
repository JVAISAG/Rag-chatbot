"""Replacement attempts do not alter a source until indexing publishes them."""
from datetime import timedelta
from threading import Event
import uuid

from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from src.workspace.jobs import queue
from src.workspace.jobs.worker import JobContext, LeaseLost, Worker
from src.workspace.library.imports import extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.questions import _scoped_chunks
from src.workspace.models import Chunk, Source, SourceReplacement, SourceRevision
import pytest


def prepare(api, root):
    client, database, first, other = api
    client.app.state.source_storage = root
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Papers'}).json()['id']
    upload = f'/api/v2/collections/{collection}/sources/upload'
    first_id = client.post(upload, files={'file': ('original.txt', b'Original evidence.')}).json()['id']
    second_id = client.post(upload, files={'file': ('other.txt', b'Other evidence.')}).json()['id']
    extract = Worker(database, {'extract': extraction_handler(database, root)})
    embed = lambda texts: [[1.0] + [0.0] * 383 for _ in texts]
    split = lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': 1}}]
    index = Worker(database, {'index': indexing_handler(database, embed=embed, split=split)})
    for _ in range(2):
        assert extract.run_once()
        assert index.run_once()
    return client, database, first, other, collection, first_id, second_id, extract, index


def test_replacement_stages_then_publishes_and_preserves_old_evidence(collection_api, tmp_path):
    client, database, first, other, collection, source_id, other_id, extract, index = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/sources/{source_id}/replace'
    assert client.patch(f'/api/v2/sources/{source_id}', json={'tags': ['Evidence'], 'reading_status': 'read'}).status_code == 200
    with database.transaction() as session:
        source = session.get(Source, uuid.UUID(source_id))
        previous = source.active_revision_id
        old_chunk = session.scalar(select(Chunk).where(Chunk.revision_id == previous))
        old_chunk_id = str(old_chunk.id)
        owner = source.owner_id
    files_before = set(tmp_path.iterdir())
    assert client.post(endpoint, files={'file': ('duplicate.txt', b'Other evidence.')}).status_code == 409
    assert set(tmp_path.iterdir()) == files_before
    same = client.post(endpoint, files={'file': ('same.txt', b'Original evidence.')})
    assert same.status_code == 202 and same.json()['unchanged']
    assert next(item for item in client.get(f'/api/v2/collections/{collection}/sources').json() if item['id'] == source_id)['reading_status'] == 'read'
    response = client.post(endpoint, files={'file': ('updated.txt', b'Updated evidence.')})
    assert response.status_code == 202
    assert client.post(endpoint, files={'file': ('again.txt', b'Updated evidence.')}).json()['job_id'] == response.json()['job_id']
    assert client.post(endpoint, files={'file': ('different.txt', b'Different evidence.')}).status_code == 409
    assert client.post(f'/api/v2/collections/{collection}/sources/upload', files={'file': ('race.txt', b'Updated evidence.')}).status_code == 409
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Original evidence.'
    assert extract.run_once()
    item = next(item for item in client.get(f'/api/v2/collections/{collection}/sources').json() if item['id'] == source_id)
    assert item['status'] == 'ready' and item['replacement_status'] == 'indexing'
    assert item['tags'] == ['Evidence'] and item['reading_status'] == 'read'
    with database.transaction() as session:
        assert session.get(Source, uuid.UUID(source_id)).active_revision_id == previous
    assert index.run_once()
    with database.transaction() as session:
        source = session.get(Source, uuid.UUID(source_id))
        assert source.active_revision_id != previous and source.filename == 'updated.txt'
        assert source.tags == ['Evidence'] and source.reading_status == 'unread'
        assert session.get(SourceRevision, previous).filename == 'original.txt'
        evidence = _scoped_chunks(session, owner, uuid.UUID(collection), [old_chunk_id])
        assert evidence[old_chunk_id]['metadata']['source'] == 'original.txt'
        assert evidence[old_chunk_id]['text'] == 'Original evidence.'
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Updated evidence.'
    stale = client.patch(f'/api/v2/sources/{source_id}', json={'tags': ['Stale'], 'reading_status': 'read', 'expected_revision_id': str(previous)})
    assert stale.status_code == 409
    with database.transaction() as session:
        source = session.get(Source, uuid.UUID(source_id))
        assert source.reading_status == 'unread' and source.tags == ['Evidence']
    use_session(client, other)
    assert client.post(endpoint, files={'file': ('stolen.txt', b'Anything')}).status_code == 404


def test_failed_replacement_keeps_original_and_allows_new_attempt(collection_api, tmp_path):
    client, database, _, _, collection, source_id, _, extract, index = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/sources/{source_id}/replace'
    assert client.post(endpoint, files={'file': ('bad.pdf', b'not a pdf')}).status_code == 202
    assert extract.run_once()
    item = next(item for item in client.get(f'/api/v2/collections/{collection}/sources').json() if item['id'] == source_id)
    assert item['status'] == 'ready' and item['replacement_status'] == 'failed'
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Original evidence.'
    assert client.post(endpoint, files={'file': ('new.txt', b'New evidence.')}).status_code == 202
    assert extract.run_once() and index.run_once()
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'New evidence.'
    with database.transaction() as session:
        assert set(session.scalars(select(SourceReplacement.status)).all()) == {'abandoned', 'published'}


def test_stale_index_lease_cannot_publish_replacement(collection_api, tmp_path):
    client, database, _, _, _, source_id, _, extract, _ = prepare(collection_api, tmp_path)
    assert client.post(f'/api/v2/sources/{source_id}/replace', files={'file': ('new.txt', b'New evidence.')}).status_code == 202
    assert extract.run_once()
    claimed = queue.claim_job(database, kinds=('index',), lease=timedelta(minutes=1))
    assert claimed
    with database.transaction() as session:
        from src.workspace.models import Job
        session.get(Job, claimed.id).lease_token = uuid.uuid4()
    handler = indexing_handler(database, embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts],
        split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': 1}}])
    with pytest.raises(LeaseLost):
        handler(claimed, JobContext(Event()))
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Original evidence.'


def test_failed_index_keeps_original_and_allows_new_attempt(collection_api, tmp_path):
    client, database, _, _, collection, source_id, _, extract, index = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/sources/{source_id}/replace'
    assert client.post(endpoint, files={'file': ('new.txt', b'New evidence.')}).status_code == 202
    assert extract.run_once()
    failing = Worker(database, {'index': indexing_handler(database,
        embed=lambda texts: [], split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': 1}}])})
    assert failing.run_once()
    item = next(item for item in client.get(f'/api/v2/collections/{collection}/sources').json() if item['id'] == source_id)
    assert item['replacement_status'] == 'failed' and item['status'] == 'ready'
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'Original evidence.'
    assert client.post(endpoint, files={'file': ('retry.txt', b'New evidence.')}).status_code == 202
    assert extract.run_once() and index.run_once()
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text'] == 'New evidence.'
