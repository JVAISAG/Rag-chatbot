import json
from pathlib import Path
import pytest
from eval.workspace import scores


def test_source_level_metrics_deduplicate_passages():
    result = scores(['a', 'b'], ['x', 'a', 'a', 'b'])
    assert result['recall_at_3'] == 1
    assert result['mrr_at_3'] == 0.5
    assert 0 < result['ndcg_at_3'] < 1
    with pytest.raises(ValueError): scores([], ['x'])


def test_reviewed_synthetic_set_has_mixed_sources_and_failure_cases():
    dataset = json.loads((Path(__file__).resolve().parents[1] / 'eval/workspace_set.json').read_text())
    ids = {item['id'] for item in dataset['sources']}
    assert {item['kind'] for item in dataset['sources']} == {'paper', 'article'}
    assert len(dataset['questions']) >= 30
    assert len({item['id'] for item in dataset['questions']}) == len(dataset['questions'])
    assert any(len(item['sources']) > 1 for item in dataset['questions'])
    assert any(not item['sources'] for item in dataset['questions'])
    assert all(set(item['sources']).issubset(ids) for item in dataset['questions'])
