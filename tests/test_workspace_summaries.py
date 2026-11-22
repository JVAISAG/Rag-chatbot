import json
from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from test_workspace_replacements import prepare
from src.workspace.jobs.worker import Worker
from src.workspace.library.summaries import FIELDS, passages, summary_handler
from src.workspace.models import Source, SourceRevision


def test_summary_context_covers_inputs_without_unnecessary_runner_reload():
    import pytest
    from src.workspace.jobs.worker import PermanentJobError
    from src.workspace.library.summaries import summary_context_tokens
    assert summary_context_tokens('Concise synthesis evidence. ' * 20) == 2048
    assert summary_context_tokens('Detailed evidence. ' * 600) == 4096
    with pytest.raises(PermanentJobError):
        summary_context_tokens('Too much evidence. ' * 2000)


def generated(prompt):
    data = json.loads(prompt.split('Evidence:\n', 1)[1])
    number = data['number'] if isinstance(data, dict) else next((ref for item in data for claims in item.values() for claim in claims for ref in claim['references']), None)
    result = {key: [] for key in FIELDS}
    if number is not None:
        result['findings'] = [{'text': 'The study reports a finding.', 'references': [number]}]
    return json.dumps(result)


def test_saved_summary_is_cited_private_and_unavailable_after_deletion(collection_api, tmp_path):
    client, database, first, other, _, source, _, _, _ = prepare(collection_api, tmp_path)
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    assert client.post(f'/api/v2/sources/{source}/summaries').json()['id'] == identity
    use_session(client, other)
    assert client.get(f'/api/v2/analyses/{identity}').status_code == 404
    assert client.post(f'/api/v2/sources/{source}/summaries').status_code == 404
    use_session(client, first)
    assert Worker(database, {'summary': summary_handler(database, generate=generated)}).run_once()
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'completed' and result['processed'] == result['total'] == 1
    assert result['result']['findings'][0]['references'] == [1]
    assert result['evidence'][0]['text'] == 'Original evidence.'
    assert client.delete(f'/api/v2/sources/{source}').status_code == 204
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'unavailable' and result['result'] is None and result['evidence'] == []


def test_summary_checkpoints_all_passages_and_resumes_model_failure(collection_api, tmp_path, monkeypatch):
    from datetime import timedelta
    from src.workspace.jobs import queue
    monkeypatch.setattr(queue, 'RETRY_DELAY', timedelta(0))
    client, database, _, _, _, source, _, _, _ = prepare(collection_api, tmp_path)
    text = 'Detailed research evidence. ' * 1500
    with database.transaction() as session:
        revision = session.get(SourceRevision, session.get(Source, __import__('uuid').UUID(source)).active_revision_id)
        revision.pages = [{'page': 1, 'text': text}]
    blocks = passages([{'page': 1, 'text': text}])
    assert ''.join(item['text'] for item in blocks) == text
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    worker = Worker(database, {'summary': summary_handler(database, generate=generated)})
    assert worker.run_once()
    assert client.get(f'/api/v2/analyses/{identity}').json()['processed'] == 1
    def failure(prompt): raise RuntimeError('model temporarily unavailable')
    assert Worker(database, {'summary': summary_handler(database, generate=failure)}).run_once()
    assert client.get(f'/api/v2/analyses/{identity}').json()['processed'] == 1
    for _ in range(len(blocks) * 3):
        if not worker.run_once(): break
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'completed' and result['processed'] == result['total'] == len(blocks)


def test_invalid_summary_citations_are_not_published(collection_api, tmp_path):
    client, database, _, _, _, source, _, _, _ = prepare(collection_api, tmp_path)
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    invalid = {key: [] for key in FIELDS}
    invalid['findings'] = [{'text': 'Claim', 'references': [999]}]
    assert Worker(database, {'summary': summary_handler(database, generate=lambda prompt: json.dumps(invalid))}).run_once()
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'failed' and result['result'] is None


def test_deletion_during_generation_cannot_publish_summary(collection_api, tmp_path):
    client, database, _, _, _, source, _, _, _ = prepare(collection_api, tmp_path)
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    def delete_during_generation(prompt):
        assert client.delete(f'/api/v2/sources/{source}').status_code == 204
        return generated(prompt)
    assert Worker(database, {'summary': summary_handler(database, generate=delete_during_generation)}).run_once()
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'unavailable' and result['result'] is None and not result['evidence']


def test_model_request_uses_schema_and_closes_client(collection_api, tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    from src.workspace.library import summaries
    client, database, _, _, _, source, _, _, _ = prepare(collection_api, tmp_path)
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    model_client = MagicMock()
    monkeypatch.setattr(summaries, 'create_client', lambda: model_client)
    def generate(client, model, prompt, **options):
        schema = options['response_format']
        assert set(schema['required']) == set(FIELDS)
        claim = schema['properties']['findings']['items']
        assert claim['properties']['references']['items']['enum'] == [1]
        assert schema['additionalProperties'] is False
        return generated(prompt)
    monkeypatch.setattr(summaries, 'generate_text', generate)
    assert Worker(database, {'summary': summaries.summary_handler(database)}).run_once()
    model_client.close.assert_called_once()
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'completed' and result['prompt_version'] == 'summary-v3'


def test_summary_validation_rejects_duplicate_references():
    import pytest
    from src.workspace.library.summaries import parse_result
    value = {key: [] for key in FIELDS}
    value['findings'] = [{'text': 'Supported claim', 'references': [1, 1]}]
    with pytest.raises(ValueError):
        parse_result(json.dumps(value), {1})


def test_summary_validation_rejects_text_the_database_cannot_store():
    import pytest
    from src.workspace.library.summaries import parse_result
    for invalid in ('A claim with \x00', 'A claim with \ud800'):
        value = {key: [] for key in FIELDS}
        value['findings'] = [{'text': invalid, 'references': [1]}]
        with pytest.raises(ValueError):
            parse_result(json.dumps(value), {1})


def test_synthesis_cannot_erase_a_reported_dimension(collection_api, tmp_path):
    client, database, _, _, _, source, _, _, _ = prepare(collection_api, tmp_path)
    with database.transaction() as session:
        revision = session.get(SourceRevision, session.get(Source, __import__('uuid').UUID(source)).active_revision_id)
        revision.pages = [{'page': 1, 'text': 'First reported finding.'}, {'page': 2, 'text': 'Second reported finding.'}]
    identity = client.post(f'/api/v2/sources/{source}/summaries').json()['id']
    def omit_during_synthesis(prompt):
        data = json.loads(prompt.split('Evidence:\n', 1)[1])
        return generated(prompt) if isinstance(data, dict) else json.dumps({key: [] for key in FIELDS})
    worker = Worker(database, {'summary': summary_handler(database, generate=omit_during_synthesis)})
    for _ in range(3):
        assert worker.run_once()
    result = client.get(f'/api/v2/analyses/{identity}').json()
    assert result['status'] == 'completed'
    assert result['result']['findings'] == [{'text': 'The study reports a finding.', 'references': [1]}]
    assert result['evidence'][0]['text'] == 'First reported finding.'
