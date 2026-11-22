from test_workspace_collections import collection_api, use_session
from test_workspace_replacements import prepare


def test_original_download_is_private_revision_pinned_and_unavailable_after_delete(collection_api, tmp_path):
    client, _, first, other, collection, source, second, extract, index = prepare(collection_api, tmp_path)
    revision = client.get(f'/api/v2/sources/{source}/text').json()['revision_id']
    url = f'/api/v2/sources/{source}/content?revision_id={revision}'
    response = client.get(url)
    assert response.content == b'Original evidence.' and response.headers['cache-control'] == 'no-store'
    assert response.headers['content-disposition'].startswith('attachment;')
    use_session(client, other)
    assert client.get(url).status_code == 404
    use_session(client, first)
    assert client.get(f'/api/v2/sources/{second}/content?revision_id={revision}').status_code == 404
    assert client.post(f'/api/v2/sources/{source}/replace', files={'file': ('new.txt', b'Changed content.')}).status_code == 202
    assert extract.run_once() and index.run_once()
    assert client.get(url).content == b'Original evidence.'
    assert client.get(f'/api/v2/sources/{source}/content').content == b'Changed content.'
    assert client.delete(f'/api/v2/sources/{source}').status_code == 204
    assert client.get(url).status_code == 404
