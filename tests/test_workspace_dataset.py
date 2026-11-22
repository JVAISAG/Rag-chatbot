import json
from pathlib import Path
import pytest
from eval.workspace_dataset import dataset_fingerprint, load_dataset


ROOT = Path(__file__).resolve().parents[1]


def test_validation_corpus_is_distinct_and_covers_missing_and_multiple_sources():
    development = load_dataset(ROOT / 'eval/workspace_set.json')
    validation = load_dataset(ROOT / 'eval/workspace_validation_set.json')
    assert validation['split'] == 'validation' and len(validation['questions']) >= 30
    assert {row['kind'] for row in validation['sources']} == {'paper', 'article'}
    assert not {row['id'] for row in development['sources']} & {row['id'] for row in validation['sources']}
    assert not {row['text'] for row in development['sources']} & {row['text'] for row in validation['sources']}
    assert any(len(row['sources']) > 1 for row in validation['questions'])
    assert sum(not row['sources'] for row in validation['questions']) == 3
    assert dataset_fingerprint(validation) != dataset_fingerprint(development)


@pytest.mark.parametrize('mutation', ['path', 'duplicate', 'unknown-source', 'contradiction', 'null-text'])
def test_invalid_corpus_cannot_create_paths_or_mislabel_answers(tmp_path, mutation):
    data = load_dataset(ROOT / 'eval/workspace_validation_set.json')
    if mutation == 'path': data['sources'][0]['id'] = '../private-file'
    if mutation == 'duplicate': data['sources'].append(data['sources'][0])
    if mutation == 'unknown-source': data['questions'][0]['sources'] = ['not-in-the-corpus']
    if mutation == 'contradiction': data['questions'][0]['sources'] = []
    if mutation == 'null-text': data['sources'][0]['text'] = 'Bad\x00text'
    path = tmp_path / 'invalid.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError): load_dataset(path)


def test_fingerprint_ignores_json_whitespace_but_detects_changed_source(tmp_path):
    data = load_dataset(ROOT / 'eval/workspace_validation_set.json')
    original = dataset_fingerprint(data)
    path = tmp_path / 'formatted.json'
    path.write_text(json.dumps(data, indent=4, sort_keys=True))
    assert dataset_fingerprint(load_dataset(path)) == original
    data['sources'][0]['text'] += ' A changed finding.'
    assert dataset_fingerprint(data) != original


def test_invalid_dataset_is_rejected_before_connecting_to_any_database(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    from scripts import verify_workspace
    monkeypatch.setattr(verify_workspace, 'load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.setattr('sys.argv', ['verify', 'evaluation', '--dataset', str(tmp_path / 'missing.json')])
    database_url = MagicMock()
    monkeypatch.setattr(verify_workspace, 'database_url', database_url)
    with pytest.raises(SystemExit) as error:
        verify_workspace.main()
    assert error.value.code == 2
    database_url.assert_not_called()
