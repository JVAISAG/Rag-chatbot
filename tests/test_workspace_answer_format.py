"""Evidence-bound identifiers and exact excerpt fallbacks use unseen labels."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from src.workspace.library.answer_format import IdentifierMismatch, decode_answer, decode_quote
from src.workspace.library.questions import answer_from_evidence


def response(text, refs=(1,)):
    return json.dumps({'claims': [{'text': text, 'references': list(refs)}], 'insufficient_evidence': False})


def test_altered_identifier_cannot_be_published_or_borrowed_from_another_reference():
    selected = [{'text': 'Evaluated on Harbor-420.'}, {'text': 'Evaluated on Harbor-42-0.'}]
    with pytest.raises(IdentifierMismatch):
        decode_answer(response('Evaluated on Harbor-42-0.'), 2, selected=selected)
    assert decode_answer(response('Evaluated on Harbor-420.'), 2, selected=selected)[1] == 'completed'
    assert decode_answer(response('Evaluated on Harbor-42-0.', (2,)), 2, selected=selected)[1] == 'completed'


def test_ordinary_technical_phrasing_is_not_a_numeric_identifier():
    assert decode_answer(response('A cross-encoder improves F1-score.'), 1,
        selected=[{'text': 'A cross-encoder improves F1.'}])[1] == 'completed'


def test_identifier_repair_gets_specific_feedback_and_preserves_actual_spelling():
    client = MagicMock()
    client.generate.side_effect = [{'response': response('Evaluated on Harbor-42-0.')},
        {'response': response('Evaluated on Harbor-420.')}]
    result = answer_from_evidence(SimpleNamespace(client=client, context_tokens=2048),
        'Which dataset?', [{'text': 'Evaluated on Harbor-420.'}], 'fixture')
    assert result == ('Evaluated on Harbor-420. [1]', 'completed')
    assert 'Identifier Harbor-42-0 is absent' in client.generate.call_args.kwargs['prompt']


def test_repeated_identifier_error_is_rejected_without_automatic_correction():
    client = MagicMock()
    client.generate.return_value = {'response': response('Evaluated on Harbor-42-0.')}
    answer, state = answer_from_evidence(SimpleNamespace(client=client, context_tokens=2048),
        'Which dataset?', [{'text': 'Evaluated on Harbor-420.'}], 'fixture')
    assert state == 'unsupported' and 'Harbor-42-0' not in answer


@pytest.mark.parametrize('quote,reference', [
    ('Invented text.', 1), ('It costs 99 dollars.', 1), ('Exact source text.', 2),
    ('Exact source text.', True), ('', 1), ('   ', 1), ('Exact source text.\x00', 1)])
def test_invalid_excerpts_are_not_rendered(quote, reference):
    with pytest.raises(ValueError):
        decode_quote(json.dumps({'quote': quote, 'reference': reference}), [{'text': 'Exact source text.'}], 0)


def test_verbatim_excerpt_is_labeled_and_does_not_claim_complete_answer():
    quote = 'Measure initial weight loading separately from later inference.'
    answer, state = decode_quote(json.dumps({'quote': quote, 'reference': 2}),
        [{'text': 'Unrelated.'}, {'text': quote}], 1)
    assert state == 'quoted_evidence' and quote in answer and answer.endswith('[2]')
    assert 'may answer only part' in answer


def test_absent_quote_has_no_fabricated_reference():
    assert decode_quote(json.dumps({'quote': '', 'reference': 0}), [{'text': 'Unrelated.'}], 0) is None


@pytest.mark.parametrize('quote,text', [('73', 'The score was 0.73.'), ('15', 'The change was -15.'),
    ('serve', 'Observe the result.'), ('6', 'The batch size was 64.'), ('0.7', 'The score was 0.73.')])
def test_excerpts_cannot_split_words_signs_or_numbers(quote, text):
    with pytest.raises(ValueError):
        decode_quote(json.dumps({'quote': quote, 'reference': 1}), [{'text': text}], 0)


def test_numeric_excerpt_can_match_a_later_complete_occurrence():
    answer, state = decode_quote(json.dumps({'quote': '64', 'reference': 1}),
        [{'text': 'Not 640: the batch size was 64.'}], 0)
    assert state == 'quoted_evidence' and '“64”' in answer
