"""Source metadata is private and shared consistently within an account."""
from test_workspace_collections import collection_api, use_session


def test_edit_metadata_is_private_shared_and_clearable(collection_api, tmp_path):
    client, database, first, second = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    one = client.post('/api/v2/collections', json={'name': 'One'}).json()['id']
    two = client.post('/api/v2/collections', json={'name': 'Two'}).json()['id']
    upload = lambda collection: client.post(f'/api/v2/collections/{collection}/sources/upload', files={'file': ('paper.txt', b'research')})
    source = upload(one).json()['id']
    assert upload(two).json()['id'] == source
    endpoint = f'/api/v2/sources/{source}'
    result = client.patch(endpoint, json={'title': '  Example title  ', 'authors': 'A. Author', 'publication_date': '2024-02-29',
        'tags': [' NLP ', 'nlp', 'Graph   learning'], 'reading_status': 'reading'})
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    for collection in (one, two):
        item = client.get(f'/api/v2/collections/{collection}/sources').json()[0]
        assert (item['title'], item['authors'], item['publication_date']) == ('Example title', 'A. Author', '2024-02-29')
        assert item['tags'] == ['NLP', 'Graph learning'] and item['reading_status'] == 'reading'
    assert client.get('/api/v2/sources').json()[0]['tags'] == ['NLP', 'Graph learning']
    assert client.patch(endpoint, json={'publication_date': '2023-02-29'}).status_code == 422
    assert client.patch(endpoint, json={'publication_date': '2024-02-29extra'}).status_code == 422
    assert client.patch(endpoint, json={'title': 'bad\u0000text'}).status_code == 422
    assert client.patch(endpoint, json={'owner_id': 'other'}).status_code == 422
    assert client.patch(endpoint, json={}).status_code == 422
    assert client.patch(endpoint, json={'title': None}, headers={'origin': 'http://evil.example'}).status_code == 403
    use_session(client, second)
    assert client.patch(endpoint, json={'title': 'stolen', 'reading_status': 'read', 'tags': ['stolen']}).status_code == 404
    use_session(client, first)
    assert client.patch(endpoint, json={'title': None, 'publication_date': None}).status_code == 200
    item = client.get(f'/api/v2/collections/{one}/sources').json()[0]
    assert item['title'] is None and item['publication_date'] is None and item['authors'] == 'A. Author'
    assert item['tags'] == ['NLP', 'Graph learning'] and item['reading_status'] == 'reading'
    assert client.patch(endpoint, json={'tags': [], 'reading_status': 'read'}).status_code == 200
    assert client.get(f'/api/v2/collections/{one}/sources').json()[0]['tags'] == []


def test_tags_and_progress_reject_invalid_metadata_before_persistence():
    from src.workspace.library.source_routes import SourceMetadataUpdate
    from pydantic import ValidationError
    import pytest
    for payload in ({'tags': ['']}, {'tags': ['a' * 33]}, {'tags': ['a,b']}, {'tags': ['bad\x00tag']},
            {'tags': ['bad\ud800']}, {'tags': [1]}, {'tags': ['a'] * 21}, {'tags': None},
            {'reading_status': 'finished'}, {'reading_status': None}, {'expected_revision_id': 'bad'}):
        with pytest.raises(ValidationError): SourceMetadataUpdate(**payload)
    assert SourceMetadataUpdate(tags=['Straße', 'STRASSE', '研究']).tags == ['Straße', '研究']


def test_attach_detach_is_private_idempotent_and_preserves_source(collection_api, tmp_path):
    client, _, first, second = collection_api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Reading'}).json()['id']
    source = client.post(f'/api/v2/collections/{collection}/sources/upload', files={'file': ('paper.txt', b'research')}).json()['id']
    membership = f'/api/v2/collections/{collection}/sources/{source}'
    assert client.delete(membership, headers={'origin': 'http://evil.example'}).status_code == 403
    assert client.delete(membership).status_code == 204
    assert client.delete(membership).status_code == 204
    assert client.get(f'/api/v2/collections/{collection}/sources').json() == []
    assert client.get('/api/v2/sources').json()[0]['id'] == source
    assert len(list(tmp_path.iterdir())) == 1
    use_session(client, second)
    other = client.post('/api/v2/collections', json={'name': 'Other'}).json()['id']
    assert client.get('/api/v2/sources').json() == []
    assert client.post(f'/api/v2/collections/{other}/sources/{source}').status_code == 404
    assert client.delete(membership).status_code == 404
    use_session(client, first)
    assert client.post(membership).status_code == 204
    assert client.post(membership).status_code == 204
    assert client.get(f'/api/v2/collections/{collection}/sources').json()[0]['id'] == source
