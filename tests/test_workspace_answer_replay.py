"""Generation evaluation uses the production citation gate without CPU models."""
import json
from unittest.mock import MagicMock
import pytest
from scripts import evaluate_workspace_answers as replay
from src.generation.llm import LLMGenerator
from src.workspace.library import questions
from test_workspace_questions import cited
from eval.workspace_dataset import dataset_fingerprint


def setup_replay(monkeypatch, tmp_path, *, ranks=('source',)):
    (tmp_path / 'eval').mkdir()
    dataset = {'scope': 'Fictional test data', 'sources': [{'id': 'source', 'kind': 'paper', 'text': 'A supported fact.'}],
        'questions': [{'id': 'one', 'question': 'Which fact?', 'answer': 'a fact', 'sources': ['source']},
            {'id': 'two', 'question': 'Which missing fact?', 'answer': None, 'sources': []}]}
    (tmp_path / 'eval/workspace_set.json').write_text(json.dumps(dataset))
    (tmp_path / 'eval/workspace_results.json').write_text(json.dumps({'complete': True, 'dataset_sha256': dataset_fingerprint(dataset), 'results': [
        {'question_id': 'one', 'mode': 'reranked', 'ranked_sources': list(ranks)}]}))
    monkeypatch.setattr(replay, 'ROOT', tmp_path)
    monkeypatch.setenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
    monkeypatch.setattr('sys.argv', ['replay', '--model', 'test-model', '--report', str(tmp_path / 'report.json')])
    client = MagicMock()
    generator = LLMGenerator(client=client, context_tokens=4096)
    monkeypatch.setattr(replay, 'LLMGenerator', lambda **kwargs: generator)
    return client


def test_replay_repairs_invalid_references_and_keeps_unanswerable_cases(monkeypatch, tmp_path):
    client = setup_replay(monkeypatch, tmp_path)
    generate = MagicMock(side_effect=[cited('Bad.', (99,)), cited('A supported fact.'),
        json.dumps({'claims': [], 'insufficient_evidence': True}), json.dumps({'quote': '', 'reference': 0})])
    monkeypatch.setattr(questions, 'generate_text', generate)
    replay.main()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['complete'] and report['question_count'] == 2
    assert [row['status'] for row in report['answers']] == ['completed', 'insufficient_evidence']
    assert report['answers'][0]['evidence'][0]['source'] == 'source'
    assert all(row['requires_semantic_review'] for row in report['answers'])
    assert generate.call_count == 4
    client.close.assert_called_once()


def test_replay_empty_retrieval_does_not_invent_an_answer(monkeypatch, tmp_path):
    client = setup_replay(monkeypatch, tmp_path, ranks=())
    generate = MagicMock(return_value=json.dumps({'claims': [], 'insufficient_evidence': True}))
    monkeypatch.setattr(questions, 'generate_text', generate)
    replay.main()
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['answers'][0]['status'] == 'no_evidence'
    assert report['answers'][0]['evidence'] == []
    assert generate.call_count == 2
    assert all('Which missing fact?' in call.args[2] for call in generate.call_args_list)
    client.close.assert_called_once()


def test_replay_refuses_remote_inference_before_loading_a_client(monkeypatch, tmp_path):
    setup_replay(monkeypatch, tmp_path)
    monkeypatch.setenv('OLLAMA_HOST', 'https://remote.example')
    factory = MagicMock()
    monkeypatch.setattr(replay, 'LLMGenerator', factory)
    with pytest.raises(SystemExit) as error:
        replay.main()
    assert error.value.code == 2
    factory.assert_not_called()


def test_replay_rejects_an_unknown_diagnostic_question(monkeypatch, tmp_path):
    setup_replay(monkeypatch, tmp_path)
    monkeypatch.setattr('sys.argv', ['replay', '--questions', 'unknown'])
    factory = MagicMock()
    monkeypatch.setattr(replay, 'LLMGenerator', factory)
    with pytest.raises(SystemExit) as error:
        replay.main()
    assert error.value.code == 2
    factory.assert_not_called()


def test_replay_refuses_ranks_from_another_corpus_before_inference(monkeypatch, tmp_path):
    setup_replay(monkeypatch, tmp_path)
    report = tmp_path / 'eval/workspace_results.json'
    data = json.loads(report.read_text())
    data['dataset_sha256'] = 'another-corpus'
    report.write_text(json.dumps(data))
    factory = MagicMock()
    monkeypatch.setattr(replay, 'LLMGenerator', factory)
    with pytest.raises(SystemExit) as error:
        replay.main()
    assert error.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize('problem', ['incomplete', 'unknown-source', 'missing-ranks'])
def test_bad_retrieval_report_never_reaches_the_model(monkeypatch, tmp_path, problem):
    setup_replay(monkeypatch, tmp_path)
    path = tmp_path / 'eval/workspace_results.json'
    data = json.loads(path.read_text())
    if problem == 'incomplete': data['complete'] = False
    if problem == 'unknown-source': data['results'][0]['ranked_sources'] = ['private-unknown-source']
    if problem == 'missing-ranks': data['results'] = []
    path.write_text(json.dumps(data))
    factory = MagicMock()
    monkeypatch.setattr(replay, 'LLMGenerator', factory)
    with pytest.raises(SystemExit) as error:
        replay.main()
    assert error.value.code == 2
    factory.assert_not_called()
