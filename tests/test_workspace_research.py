from test_workspace_collections import collection_api, use_session
from test_workspace_replacements import prepare
from test_workspace_summaries import generated
from src.workspace.jobs.worker import Worker
from src.workspace.library.summaries import summary_handler


def research(api, root):
    client, database, first, other, collection, one, two, _, _ = prepare(api, root)
    summaries = []
    for source in (one, two):
        identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
        assert Worker(database, {'summary': summary_handler(database, generate=generated)}).run_once()
        summaries.append(identity)
    return client, database, first, other, collection, one, two, summaries


def test_comparison_is_private_pinned_and_masks_detached_or_deleted_evidence(collection_api, tmp_path):
    client, _, first, other, collection, one, two, summaries = research(collection_api, tmp_path)
    endpoint = f'/api/v2/collections/{collection}/comparisons'
    assert client.post(endpoint, json={'summary_ids': [summaries[0]]}).status_code == 422
    assert client.post(endpoint, json={'summary_ids': [summaries[0], summaries[0]]}).status_code == 422
    identity = client.post(endpoint, json={'summary_ids': summaries}).json()['id']
    result = client.get(f'/api/v2/comparisons/{identity}').json()
    assert len(result['sources']) == 2 and all(row['available'] for row in result['sources'])
    original_revisions = [row['revision_id'] for row in result['sources']]
    assert 'evaluation conditions' in result['caution']
    use_session(client, other)
    assert client.get(f'/api/v2/comparisons/{identity}').status_code == 404
    assert client.post(endpoint, json={'summary_ids': summaries}).status_code == 404
    use_session(client, first)
    assert client.delete(f'/api/v2/collections/{collection}/sources/{one}').status_code == 204
    result = client.get(f'/api/v2/comparisons/{identity}').json()
    assert not result['sources'][0]['available'] and result['sources'][0]['evidence'] == []
    assert client.post(f'/api/v2/collections/{collection}/sources/{one}').status_code == 204
    assert [row['revision_id'] for row in client.get(f'/api/v2/comparisons/{identity}').json()['sources']] == original_revisions
    assert client.delete(f'/api/v2/sources/{two}').status_code == 204
    result = client.get(f'/api/v2/comparisons/{identity}').json()
    assert result['sources'][1]['result'] is None and result['sources'][0]['available']


def test_notes_crud_conflicts_private_attachments_and_export(collection_api, tmp_path):
    client, _, first, other, collection, one, _, summaries = research(collection_api, tmp_path)
    comparison = client.post(f'/api/v2/collections/{collection}/comparisons', json={'summary_ids': summaries}).json()['id']
    body = {'title': 'My research', 'markdown': 'My own observations.', 'analysis_ids': [summaries[0]], 'comparison_ids': [comparison]}
    endpoint = f'/api/v2/collections/{collection}/notes'
    assert client.post(endpoint, json={**body, 'title': '  '}).status_code == 422
    assert client.post(endpoint, json={**body, 'markdown': 'bad\u0000text'}).status_code == 422
    note = client.post(endpoint, json=body).json()
    path = f"/api/v2/notes/{note['id']}"
    export = client.get(path + '/export')
    assert export.status_code == 200 and 'attachment;' in export.headers['content-disposition']
    assert 'My own observations.' in export.text and 'The study reports a finding.' in export.text
    assert 'Original evidence.' not in export.text and 'Other evidence.' not in export.text
    assert f"[{summaries[0]}/1]" in export.text
    update = {**body, 'markdown': 'Updated observations.', 'version': note['version']}
    changed = client.patch(path, json=update)
    assert changed.status_code == 200 and changed.json()['version'] == 2
    assert client.patch(path, json=update).status_code == 409
    use_session(client, other)
    assert client.get(path).status_code == 404 and client.get(path + '/export').status_code == 404
    assert client.delete(path).status_code == 404 and client.patch(path, json=update).status_code == 404
    other_collection = client.post('/api/v2/collections', json={'name': 'Mine'}).json()['id']
    assert client.post(f'/api/v2/collections/{other_collection}/notes', json=body).status_code == 404
    use_session(client, first)
    assert client.delete(f'/api/v2/collections/{collection}/sources/{one}').status_code == 204
    assert client.post(endpoint, json=body).status_code == 404
    changed = client.patch(path, json={**update, 'version': 2, 'markdown': 'Edited after detachment.'})
    assert changed.status_code == 200 and changed.json()['version'] == 3
    assert 'Evidence unavailable.' in client.get(path + '/export').text
    assert client.delete(f'/api/v2/sources/{one}').status_code == 204
    assert 'Evidence unavailable.' in client.get(path + '/export').text
    assert client.get(path).json()['markdown'] == 'Edited after detachment.'
    assert client.delete(f'/api/v2/collections/{collection}').status_code == 409
    assert client.delete(path).status_code == 204 and client.get(path).status_code == 404
    assert client.delete(f'/api/v2/collections/{collection}').status_code == 204
    assert client.get(f'/api/v2/comparisons/{comparison}').status_code == 404
    assert client.get('/api/v2/sources').json(), 'Deleting a collection must preserve the remaining library source.'
