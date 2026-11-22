"""Queued article imports preserve ownership, originals, and searchable text."""
from datetime import timedelta
from threading import Event
import uuid

from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from src.workspace.jobs import queue
from src.workspace.jobs.worker import JobContext, LeaseLost, Worker
from src.workspace.library.imports import extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.url_imports import url_import_handler
from src.workspace.library.web_fetch import FetchedPage, UnsafeURL
from src.workspace.models import Source, SourceRevision
import pytest


HTML = b'<html><head><title>Training study</title><meta name="author" content="A. Researcher"></head><body><article><p>The research study tested a new training method and reported improvements on a controlled evaluation dataset.</p></article></body></html>'


def test_article_import_extracts_and_indexes_with_private_job_status(collection_api, tmp_path):
    client, database, first, second = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Articles'}).json()['id']
    path = f'/api/v2/collections/{collection}/sources/import-url'
    assert client.post(path, json={'url': 'file:///secret'}).status_code == 422
    assert client.post(path, json={'url': 'https://example.org/story'}, headers={'origin': 'http://evil.test'}).status_code == 403
    response = client.post(path, json={'url': 'https://example.org/story#fragment'})
    assert response.status_code == 202
    job_id = response.json()['job_id']
    assert client.get(f'/api/v2/jobs/{job_id}').json()['status'] == 'pending'
    use_session(client, second)
    assert client.get(f'/api/v2/jobs/{job_id}').status_code == 404
    assert client.post(path, json={'url': 'https://example.org/story'}).status_code == 404
    use_session(client, first)
    calls = []
    def fetch(url):
        calls.append(url)
        return FetchedPage('https://example.org/story', 'text/html', HTML)
    assert Worker(database, {'url_import': url_import_handler(database, tmp_path, fetch=fetch)}).run_once()
    status = client.get(f'/api/v2/jobs/{job_id}').json()
    assert status['status'] == 'completed' and status['source_id']
    assert calls == ['https://example.org/story']
    source_id = status['source_id']
    assert Worker(database, {'extract': extraction_handler(database, tmp_path)}).run_once()
    embed = lambda texts: [[1.0] + [0.0] * 383 for _ in texts]
    split = lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': None}}]
    assert Worker(database, {'index': indexing_handler(database, embed=embed, split=split)}).run_once()
    item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
    assert item['status'] == 'ready' and item['original_url'] == 'https://example.org/story'
    assert item['title'] == 'Training study'
    assert 'controlled evaluation dataset' in client.get(f'/api/v2/sources/{source_id}/text').json()['pages'][0]['text']
    with database.transaction() as session:
        source = session.get(Source, uuid.UUID(source_id))
        revision = session.get(SourceRevision, source.active_revision_id)
        assert revision.original_url == source.original_url
        assert (tmp_path / source.storage_key).read_bytes() == HTML
    # Re-importing identical content attaches the existing source.
    another = client.post(path, json={'url': 'https://example.org/story'}).json()['job_id']
    assert Worker(database, {'url_import': url_import_handler(database, tmp_path, fetch=fetch)}).run_once()
    assert client.get(f'/api/v2/jobs/{another}').json()['source_id'] == source_id
    assert len(client.get(f'/api/v2/collections/{collection}/sources').json()) == 1


def test_rejected_destination_and_stale_lease_do_not_create_sources(collection_api, tmp_path):
    client, database, first, _ = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Unsafe'}).json()['id']
    path = f'/api/v2/collections/{collection}/sources/import-url'
    job = client.post(path, json={'url': 'http://127.0.0.1/secret'}).json()['job_id']
    def reject(url):
        raise UnsafeURL('private')
    assert Worker(database, {'url_import': url_import_handler(database, tmp_path, fetch=reject)}).run_once()
    assert client.get(f'/api/v2/jobs/{job}').json()['status'] == 'failed'
    assert client.get(f'/api/v2/collections/{collection}/sources').json() == []
    client.post(path, json={'url': 'https://example.org/story'})
    claimed = queue.claim_job(database, kinds=('url_import',), lease=timedelta(minutes=1))
    def expired(url):
        from src.workspace.models import Job
        with database.transaction() as session:
            session.get(Job, claimed.id).lease_token = uuid.uuid4()
        return FetchedPage(url, 'text/html', HTML)
    with pytest.raises(LeaseLost):
        url_import_handler(database, tmp_path, fetch=expired)(claimed, JobContext(Event()))
    assert client.get(f'/api/v2/collections/{collection}/sources').json() == []
    assert list(tmp_path.iterdir()) == []


def test_pdf_url_uses_existing_document_loader(collection_api, tmp_path, monkeypatch):
    from src.workspace.library import imports
    client, database, first, _ = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'PDF'}).json()['id']
    job = client.post(f'/api/v2/collections/{collection}/sources/import-url', json={'url': 'https://example.org/paper.pdf'}).json()['job_id']
    assert Worker(database, {'url_import': url_import_handler(database, tmp_path,
        fetch=lambda url: FetchedPage(url, 'application/pdf', b'%PDF test'))}).run_once()
    source_id = client.get(f'/api/v2/jobs/{job}').json()['source_id']
    seen = []
    def load(path, source):
        seen.append(path)
        return [{'text': 'The PDF passage.', 'metadata': {'page': 2}}]
    monkeypatch.setattr(imports, 'load_document', load)
    assert Worker(database, {'extract': extraction_handler(database, tmp_path)}).run_once()
    assert seen[0].endswith('.pdf')
    assert client.get(f'/api/v2/sources/{source_id}/text').json()['pages'] == [{'text': 'The PDF passage.', 'page': 2}]
