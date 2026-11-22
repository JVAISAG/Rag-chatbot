"""Question lifecycle, citation repair, and private conversation access."""
from types import SimpleNamespace
import json
from unittest.mock import MagicMock
import uuid
import pytest
from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from src.workspace.jobs.worker import Worker
from src.workspace.library.imports import extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.questions import ANSWER_PROMPT_VERSION, answer_handler
from src.workspace.library.answer_format import ANSWER_SYSTEM_PROMPT, answer_prompt, decode_answer
from src.workspace.models import Chunk, CollectionSource, Job, QuestionTurn


def cited(text='Supported.', references=(1,)):
    return json.dumps({'claims': [{'text': text, 'references': list(references)}], 'insufficient_evidence': False})


def setup_question(api, tmp_path, *, with_source=True):
    client, database, first, second = api
    client.app.state.source_storage = tmp_path
    use_session(client, first)
    collection = client.post('/api/v2/collections', json={'name': 'Questions'}).json()['id']
    hits = []
    if with_source:
        client.post(f'/api/v2/collections/{collection}/sources/upload', files={'file': ('paper.txt', b'Research supports this result.')})
        Worker(database, {'extract': extraction_handler(database, tmp_path)}).run_once()
        Worker(database, {'index': indexing_handler(database, embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts], split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': 1}}])}).run_once()
        with database.transaction() as session:
            chunk = session.scalar(select(Chunk))
            hits = [{'id': str(chunk.id), 'text': chunk.text, 'metadata': {}}]
    conversation = client.post(f'/api/v2/collections/{collection}/conversations').json()['id']
    turn = client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'What is supported?'})
    assert turn.status_code == 202
    generator = SimpleNamespace(_prepare_context=lambda query, items: ('bounded evidence prompt', items), condense_query=lambda query, history: query)
    return client, database, second, conversation, turn.json()['id'], hits, generator


def test_citation_repair_persistence_and_account_isolation(collection_api, tmp_path):
    client, database, other, conversation, turn, hits, generator = setup_question(collection_api, tmp_path)
    assert client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'Another?'}).status_code == 409
    responses = iter([cited('Invalid.', (99,)), cited('Supported result.')])
    handler = answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=lambda prompt: next(responses))
    assert Worker(database, {'answer': handler}).run_once()
    result = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert result['status'] == 'completed' and result['answer'] == 'Supported result. [1]'
    assert result['evidence'][0]['available'] and result['evidence'][0]['metadata']['page'] == 1
    assert result['evidence'][0]['text'] == 'Research supports this result.'
    with database.transaction() as session:
        assert session.get(QuestionTurn, uuid.UUID(turn)).prompt_version == ANSWER_PROMPT_VERSION
    use_session(client, other)
    assert client.get(f'/api/v2/conversations/{conversation}').status_code == 404
    assert client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'Steal?'}).status_code == 404


def test_empty_evidence_does_not_invoke_model(collection_api, tmp_path):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path, with_source=False)
    generate = MagicMock()
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=generate)}).run_once()
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['status'] == 'no_evidence'
    generate.assert_not_called()


@pytest.mark.parametrize('quoted', [False, True])
def test_followup_retains_the_question_after_an_abstention(collection_api, tmp_path, quoted):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    outputs = iter([json.dumps({'claims': [], 'insufficient_evidence': True}),
        json.dumps({'quote': 'Research supports this result.' if quoted else '', 'reference': 1 if quoted else 0}), cited('A supported fact.')])
    worker = Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits,
        generator_factory=lambda: generator, generate=lambda prompt: next(outputs))})
    worker.run_once()
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['status'] == ('quoted_evidence' if quoted else 'insufficient_evidence')
    generator.condense_query = MagicMock(return_value='Standalone follow-up')
    followup = client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'What about the other setting?'})
    assert followup.status_code == 202
    worker.run_once()
    history = generator.condense_query.call_args.args[1]
    assert history[0] == {'role': 'user', 'content': 'What is supported?'}
    turns = client.get(f'/api/v2/conversations/{conversation}').json()['turns']
    assert next(turn for turn in turns if turn['id'] == followup.json()['id'])['status'] == 'completed'


@pytest.mark.parametrize('fails', [False, True])
def test_answer_worker_closes_its_model_client(collection_api, tmp_path, monkeypatch, fails):
    from src.workspace.library import questions
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    generator.client = MagicMock()
    monkeypatch.setattr(questions, 'LLMGenerator', lambda **kwargs: generator)
    generate = MagicMock(side_effect=RuntimeError('model unavailable')) if fails else MagicMock(return_value=cited())
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generate=generate)}).run_once()
    generator.client.close.assert_called_once()
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['status'] == ('pending' if fails else 'completed')


def test_request_key_retries_are_idempotent(collection_api, tmp_path):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=lambda prompt: cited())}).run_once()
    key = str(uuid.uuid4())
    endpoint = f'/api/v2/conversations/{conversation}/messages'
    first = client.post(endpoint, json={'question': 'Follow-up?'}, headers={'Idempotency-Key': key})
    second = client.post(endpoint, json={'question': 'Follow-up?'}, headers={'Idempotency-Key': key})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert client.post(endpoint, json={'question': 'Different?'}, headers={'Idempotency-Key': key}).status_code == 409


def test_question_database_errors_and_input_are_sanitized(collection_api, tmp_path, monkeypatch):
    from src.workspace.database import DatabaseConfigurationError
    from src.workspace.library import question_routes
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    endpoint = f'/api/v2/conversations/{conversation}/messages'
    assert client.post(endpoint, json={'question': '   '}).status_code == 422
    assert client.post(endpoint, json={'question': 'private question', 'owner_id': str(uuid.uuid4())}).status_code == 422
    def fail(*args):
        raise DatabaseConfigurationError('private database details')
    monkeypatch.setattr(question_routes, 'enqueue_question', fail)
    response = client.post(endpoint, json={'question': 'Question'})
    assert response.status_code == 503 and 'private database details' not in response.text


def test_followup_uses_history_and_exhausted_model_failure_is_visible(collection_api, tmp_path, monkeypatch):
    from datetime import timedelta
    from src.workspace.jobs import queue
    monkeypatch.setattr(queue, 'RETRY_DELAY', timedelta(0))
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    instance = Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=lambda prompt: cited())})
    instance.run_once()
    generator.condense_query = MagicMock(return_value='Standalone follow-up')
    client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'And why?'})
    retrieve = MagicMock(return_value=hits)
    failing_model = MagicMock(side_effect=RuntimeError('private failure'))
    failing = Worker(database, {'answer': answer_handler(database, retrieve=retrieve, generator_factory=lambda: generator, generate=failing_model)})
    for _ in range(3):
        failing.run_once()
    generator.condense_query.assert_called_once()
    assert retrieve.call_args.args[-1] == 'Standalone follow-up'
    assert 'Standalone follow-up' in failing_model.call_args.args[0]
    result = client.get(f'/api/v2/conversations/{conversation}').json()['turns']
    assert any(turn['status'] == 'failed' and turn['answer'] is None for turn in result)
    assert any(turn['question'] == 'And why?' for turn in result)


def test_invalid_citations_are_never_published(collection_api, tmp_path):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    generate = MagicMock(return_value=cited('Unverified claim.', (77,)))
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=generate)}).run_once()
    result = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert result['status'] == 'unsupported'
    assert '[77]' not in result['answer'] and generate.call_count == 2


def test_model_failure_reuses_persisted_evidence_on_retry(collection_api, tmp_path, monkeypatch):
    from datetime import timedelta
    from src.workspace.jobs import queue
    monkeypatch.setattr(queue, 'RETRY_DELAY', timedelta(0))
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    retrieve = MagicMock(return_value=hits)
    generate = MagicMock(side_effect=[RuntimeError('private error'), cited()])
    instance = Worker(database, {'answer': answer_handler(database, retrieve=retrieve, generator_factory=lambda: generator, generate=generate)})
    instance.run_once()
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['status'] == 'pending'
    instance.run_once()
    assert retrieve.call_count == 1
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['status'] == 'completed'


def test_initial_queue_wait_is_saved_before_retrieval_failure_and_not_inflated_on_retry(collection_api, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from src.workspace.jobs import queue
    from src.workspace.library import questions
    frozen = datetime.now(timezone.utc)
    class Clock(datetime):
        current = frozen
        @classmethod
        def now(cls, tz=None): return cls.current
    monkeypatch.setattr(questions, 'datetime', Clock)
    monkeypatch.setattr(queue, 'RETRY_DELAY', timedelta(0))
    client, database, _, conversation, turn_id, hits, generator = setup_question(collection_api, tmp_path)
    with database.transaction() as session:
        session.get(QuestionTurn, uuid.UUID(turn_id)).created_at = frozen - timedelta(seconds=11)
    retrieve = MagicMock(side_effect=[RuntimeError('temporary retrieval error'), hits])
    worker = Worker(database, {'answer': answer_handler(database, retrieve=retrieve,
        generator_factory=lambda: generator, generate=lambda prompt: cited())})
    assert worker.run_once()
    first = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert first['status'] == 'pending' and first['timings']['initial_queue_seconds'] == 11
    Clock.current = frozen + timedelta(seconds=50)
    assert worker.run_once()
    second = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert second['status'] == 'completed' and second['timings']['initial_queue_seconds'] == 11


def test_removed_evidence_blocks_publication(collection_api, tmp_path):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    def generate(prompt):
        with database.transaction() as session:
            session.delete(session.scalar(select(CollectionSource)))
        return cited()
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=generate)}).run_once()
    result = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert result['status'] == 'unavailable' and result['evidence'] == []


def test_detached_evidence_is_hidden_and_available_again_after_reattach(collection_api, tmp_path):
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=lambda prompt: cited())}).run_once()
    with database.transaction() as session:
        membership = session.scalar(select(CollectionSource))
        collection_id, source_id = membership.collection_id, membership.source_id
    path = f'/api/v2/collections/{collection_id}/sources/{source_id}'
    assert client.delete(path).status_code == 204
    reference = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['evidence'][0]
    assert not reference['available'] and reference['text'] == ''
    assert client.post(path).status_code == 204
    reference = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['evidence'][0]
    assert reference['available'] and reference['text'] == 'Research supports this result.'


def test_stale_answer_worker_cannot_publish(collection_api, tmp_path):
    client, database, _, conversation, turn, hits, generator = setup_question(collection_api, tmp_path)
    def generate(prompt):
        with database.transaction() as session:
            question = session.get(QuestionTurn, uuid.UUID(turn))
            session.get(Job, question.job_id).lease_token = uuid.uuid4()
        return cited()
    Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits, generator_factory=lambda: generator, generate=generate)}).run_once()
    assert client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]['answer'] is None


@pytest.mark.parametrize('references', [[], [0], [9], ['1,2'], ['1:64'], [True], ['١'], [99999999999999999999999999]])
def test_unsupported_citation_references_are_rejected(references):
    with pytest.raises(ValueError):
        decode_answer(cited('Claim.', references), 2)


@pytest.mark.parametrize('context_tokens', [2048, 4096])
def test_citation_instructions_leave_room_for_system_and_output(context_tokens):
    from src.chunking.text_splitter import num_tokens_from_string
    from src.generation.llm import LLMGenerator
    generator = LLMGenerator(client=MagicMock(), context_tokens=context_tokens)
    chunks = [{'text': 'Short research evidence. ' * 20, 'metadata': {'source': f'paper-{number}.txt'}} for number in range(5)]
    chunks.append({'text': 'Long research evidence. ' * 2000, 'metadata': {'source': 'paper-5.txt'}})
    prompt, selected = generator._prepare_context('What is supported?', chunks)
    assert len(selected) == 6
    for repair in (False, True):
        rendered = answer_prompt('What is supported?', selected, repair=repair,
            feedback=('Identifier ' + 'X' * 80 + ' is absent from its cited passages. Copy the technical identifier from the evidence exactly.') if repair else '')
        assert num_tokens_from_string(rendered + ANSWER_SYSTEM_PROMPT) + 512 + 128 <= context_tokens


def test_explicit_abstention_does_not_require_a_fabricated_citation():
    answer, state = decode_answer(json.dumps({'claims': [], 'insufficient_evidence': True}), 2)
    assert state == 'insufficient_evidence' and '[' not in answer


@pytest.mark.parametrize('result', [
    {'claims': [], 'insufficient_evidence': False},
    {'claims': [{'text': 'A claim.', 'references': [1]}], 'insufficient_evidence': True},
    {'claims': [{'text': 'A claim [99]', 'references': [1]}], 'insufficient_evidence': False},
    {'claims': [{'text': '\u0000', 'references': [1]}], 'insufficient_evidence': False},
    {'claims': [{'text': 'A claim.', 'references': [1.0]}], 'insufficient_evidence': False},
    {'claims': [], 'insufficient_evidence': 'true'},
])
def test_malformed_or_contradictory_claims_are_rejected(result):
    with pytest.raises(ValueError):
        decode_answer(json.dumps(result), 2)


def test_technical_square_brackets_are_not_confused_with_reference_ids():
    answer, state = decode_answer(cited('The [CLS] token represents the sequence.', (1, 1)), 1)
    assert state == 'completed' and answer == 'The [CLS] token represents the sequence. [1]'


def test_production_generation_requests_a_bounded_schema():
    from src.workspace.library.questions import answer_from_evidence
    client = MagicMock()
    client.generate.return_value = {'response': cited('A supported fact.')}
    generator = SimpleNamespace(client=client, context_tokens=4096)
    result = answer_from_evidence(generator, 'Which fact?', [{'text': 'A supported fact.', 'metadata': {}}], 'test-model')
    assert result == ('A supported fact. [1]', 'completed')
    schema = client.generate.call_args.kwargs['format']
    assert schema['properties']['claims']['items']['properties']['references']['items']['maximum'] == 1


def test_focused_abstention_check_keeps_original_reference_numbers():
    from src.workspace.library.questions import answer_from_evidence
    client = MagicMock()
    abstention = json.dumps({'claims': [], 'insufficient_evidence': True})
    client.generate.side_effect = [{'response': abstention}, {'response': abstention},
        {'response': json.dumps({'quote': 'The cache uses owner and revision IDs.', 'reference': 2})}]
    selected = [{'text': 'Unrelated first passage.', 'metadata': {'source': 'a.txt'}},
        {'text': 'The cache uses owner and revision IDs.', 'metadata': {'source': 'b.txt'}}]
    answer, state = answer_from_evidence(SimpleNamespace(client=client, context_tokens=2048), 'What identifies the cache?', selected, 'test')
    assert state == 'quoted_evidence' and answer.endswith('[2]')
    request = client.generate.call_args.kwargs
    assert 'Passage [2]' in request['prompt'] and 'Unrelated first passage.' not in request['prompt']
    assert request['format']['properties']['reference']['enum'] == [0, 2]


def test_focused_check_rejects_references_to_hidden_passages():
    from src.workspace.library.questions import answer_from_evidence
    client = MagicMock()
    client.generate.side_effect = [
        {'response': json.dumps({'claims': [], 'insufficient_evidence': True})},
        {'response': json.dumps({'quote': 'First passage.', 'reference': 2})},
        {'response': json.dumps({'quote': 'Second passage.', 'reference': 1})}]
    selected = [{'text': 'First passage.'}, {'text': 'Second passage.'}]
    answer, state = answer_from_evidence(SimpleNamespace(client=client, context_tokens=2048), 'Missing detail?', selected, 'test')
    assert state == 'insufficient_evidence' and '[' not in answer
    assert client.generate.call_count == 3


def test_optional_focused_outage_preserves_the_valid_abstention():
    from src.workspace.library.questions import answer_from_evidence
    from src.errors import ModelUnavailableError
    generate = MagicMock(side_effect=[json.dumps({'claims': [], 'insufficient_evidence': True}), ModelUnavailableError('offline')])
    result = answer_from_evidence(SimpleNamespace(), 'Missing detail?', [{'text': 'One.'}, {'text': 'Two.'}], 'test', generate=generate)
    assert result[1] == 'insufficient_evidence' and generate.call_count == 2
