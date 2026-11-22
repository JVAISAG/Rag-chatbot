from types import SimpleNamespace
from sqlalchemy import select
from test_workspace_collections import collection_api
from test_workspace_replacements import prepare
from src.workspace.jobs.worker import Worker
from src.workspace.library.questions import answer_handler
from test_workspace_questions import cited
from src.workspace.models import Chunk


def test_conversation_scope_filters_even_untrusted_retriever_results(collection_api, tmp_path):
    client, database, _, _, collection, one, two, _, _ = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/collections/{collection}/conversations'
    assert client.post(endpoint, json={'source_ids': []}).status_code == 422
    assert client.post(endpoint, json={'source_ids': ['00000000-0000-0000-0000-000000000001']}).status_code == 404
    conversation = client.post(endpoint, json={'source_ids': [one]}).json()['id']
    with database.transaction() as session:
        hits = [{'id': str(chunk.id)} for chunk in session.scalars(select(Chunk))]
    def retrieve(database, owner, collection_id, query, **options):
        assert options['source_ids'] == [one]
        return hits
    generator = SimpleNamespace(_prepare_context=lambda query, items: ('prompt', items))
    worker = Worker(database, {'answer': answer_handler(database, retrieve=retrieve, generator_factory=lambda: generator, generate=lambda prompt: cited())})
    client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'What is supported?'})
    assert worker.run_once()
    turn = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert len(turn['evidence']) == 1 and turn['evidence'][0]['metadata']['source_id'] == one
    assert client.get(endpoint).json()[0]['source_ids'] == [one]
    assert client.delete(f'/api/v2/collections/{collection}/sources/{one}').status_code == 204
    assert not client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['evidence'][0]['available']
