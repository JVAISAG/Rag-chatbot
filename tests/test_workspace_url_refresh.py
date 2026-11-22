"""URL refreshes retain the active revision until a new index is complete."""
from datetime import timedelta
from threading import Event
import uuid

import pytest
from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from test_workspace_url_imports import HTML
from src.workspace.jobs import queue
from src.workspace.jobs.worker import JobContext, LeaseLost, Worker
from src.workspace.library.imports import extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.url_imports import url_import_handler, url_refresh_handler
from src.workspace.library.web_fetch import FetchedPage, UnsafeURL
from src.workspace.models import Job, Source, SourceRevision


NEW_HTML = b'<html><body><article><p>The updated research study reports a different training method and new evaluation findings across the experiments.</p></article></body></html>'


def prepare(api, root):
    client, database, first, second = api
    client.app.state.source_storage = root
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Articles'}).json()['id']
    path = f'/api/v2/collections/{collection}/sources/import-url'
    job = client.post(path, json={'url': 'https://example.org/story'}).json()['job_id']
    assert Worker(database, {'url_import': url_import_handler(database, root, fetch=lambda url: FetchedPage(url, 'text/html', HTML))}).run_once()
    source = client.get(f'/api/v2/jobs/{job}').json()['source_id']
    extract = Worker(database, {'extract': extraction_handler(database, root)})
    index = Worker(database, {'index': indexing_handler(database,
        embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts],
        split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': None}}])})
    assert extract.run_once() and index.run_once()
    return client, database, first, second, collection, source, extract, index


def test_unchanged_and_changed_refresh_publish_atomically(collection_api, tmp_path):
    client, database, first, other, collection, source_id, extract, index = prepare(collection_api, tmp_path)
    path = f'/api/v2/sources/{source_id}/refresh'
    assert client.patch(f'/api/v2/sources/{source_id}', json={'tags': ['Articles'], 'reading_status': 'read'}).status_code == 200
    with database.transaction() as session:
        initial = session.get(Source, uuid.UUID(source_id)).active_revision_id
    first_job = client.post(path).json()['job_id']
    assert client.post(path).json()['job_id'] == first_job
    assert client.post(f'/api/v2/sources/{source_id}/replace', files={'file': ('new.txt', b'new content')}).status_code == 409
    use_session(client, other)
    assert client.post(path).status_code == 404
    use_session(client, first)
    assert Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path, fetch=lambda url: FetchedPage(url, 'text/html', HTML))}).run_once()
    item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
    assert item['refresh_outcome'] == 'unchanged'
    assert item['tags'] == ['Articles'] and item['reading_status'] == 'read'
    with database.transaction() as session:
        assert session.get(Source, uuid.UUID(source_id)).active_revision_id == initial
        assert len(session.scalars(select(SourceRevision)).all()) == 1
    assert client.post(path).status_code == 202
    fetch = lambda url: FetchedPage('https://example.org/updated', 'text/html', NEW_HTML)
    assert Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path, fetch=fetch)}).run_once()
    item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
    assert item['refresh_outcome'] == 'staged' and item['replacement_status'] == 'processing'
    assert 'controlled evaluation dataset' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']
    assert extract.run_once()
    with database.transaction() as session:
        assert session.get(Source, uuid.UUID(source_id)).active_revision_id == initial
    assert index.run_once()
    with database.transaction() as session:
        source = session.get(Source, uuid.UUID(source_id))
        assert source.active_revision_id != initial and source.original_url == 'https://example.org/updated'
        assert source.tags == ['Articles'] and source.reading_status == 'unread'
        assert session.get(SourceRevision, initial).original_url == 'https://example.org/story'
        assert session.get(SourceRevision, source.active_revision_id).original_url == 'https://example.org/updated'
    assert 'different training method' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']


def test_duplicate_and_failed_refresh_leave_both_sources_unchanged(collection_api, tmp_path):
    client, database, _, _, collection, source_id, extract, index = prepare(collection_api, tmp_path)
    path = f'/api/v2/collections/{collection}/sources/import-url'
    other_job = client.post(path, json={'url': 'https://example.org/second'}).json()['job_id']
    assert Worker(database, {'url_import': url_import_handler(database, tmp_path, fetch=lambda url: FetchedPage(url, 'text/html', NEW_HTML))}).run_once()
    other_id = client.get(f'/api/v2/jobs/{other_job}').json()['source_id']
    assert extract.run_once() and index.run_once()
    before = set(tmp_path.iterdir())
    refresh = f'/api/v2/sources/{source_id}/refresh'
    client.post(refresh)
    assert Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path, fetch=lambda url: FetchedPage(url, 'text/html', NEW_HTML))}).run_once()
    item = next(value for value in client.get(f'/api/v2/collections/{collection}/sources').json() if value['id'] == source_id)
    assert item['refresh_outcome'] == 'duplicate' and set(tmp_path.iterdir()) == before
    assert 'controlled evaluation dataset' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']
    assert 'different training method' in client.get(f'/api/v2/sources/{other_id}/text').json()['pages'][0]['text']
    client.post(refresh)
    def denied(url): raise UnsafeURL('private')
    assert Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path, fetch=denied)}).run_once()
    item = next(value for value in client.get(f'/api/v2/collections/{collection}/sources').json() if value['id'] == source_id)
    assert item['refresh_status'] == 'failed' and item['status'] == 'ready'
    assert set(tmp_path.iterdir()) == before


def test_stale_refresh_lease_cannot_stage_file(collection_api, tmp_path):
    client, database, _, _, _, source_id, _, _ = prepare(collection_api, tmp_path)
    assert client.post(f'/api/v2/sources/{source_id}/refresh').status_code == 202
    claimed = queue.claim_job(database, kinds=('url_refresh',), lease=timedelta(minutes=1))
    before = set(tmp_path.iterdir())
    def lose_lease(url):
        with database.transaction() as session:
            session.get(Job, claimed.id).lease_token = uuid.uuid4()
        return FetchedPage(url, 'text/html', NEW_HTML)
    with pytest.raises(LeaseLost):
        url_refresh_handler(database, tmp_path, fetch=lose_lease)(claimed, JobContext(Event()))
    assert set(tmp_path.iterdir()) == before
    assert 'controlled evaluation dataset' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']


def test_failed_refresh_index_leaves_original_and_can_retry(collection_api, tmp_path):
    client, database, _, _, collection, source_id, extract, index = prepare(collection_api, tmp_path)
    path = f'/api/v2/sources/{source_id}/refresh'
    assert client.patch(f'/api/v2/sources/{source_id}', json={'tags': ['Keep'], 'reading_status': 'read'}).status_code == 200
    worker = Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path,
        fetch=lambda url: FetchedPage(url, 'text/html', NEW_HTML))})
    assert client.post(path).status_code == 202
    assert worker.run_once() and extract.run_once()
    failing = Worker(database, {'index': indexing_handler(database, embed=lambda texts: [],
        split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': None}}])})
    assert failing.run_once()
    item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
    assert item['replacement_status'] == 'failed' and item['status'] == 'ready'
    assert item['tags'] == ['Keep'] and item['reading_status'] == 'read'
    assert 'controlled evaluation dataset' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']
    assert client.post(path).status_code == 202
    assert worker.run_once() and extract.run_once() and index.run_once()
    assert 'different training method' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']
    item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
    assert item['tags'] == ['Keep'] and item['reading_status'] == 'unread'
