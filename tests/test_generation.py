from unittest.mock import MagicMock

import pytest

from src.chunking.text_splitter import num_tokens_from_string
from src.errors import ModelUnavailableError
from src.generation.llm import LLMGenerator


def generator(response="This is the answer [1]."):
    client = MagicMock()
    client.generate.return_value = {"response": response}
    return LLMGenerator(client=client), client


def test_condense_query():
    model, _ = generator("Standalone Question: What is a transformer?")
    assert model.condense_query("What is it?", [{"role": "user", "content": "Tell me about it."}]) == "What is a transformer?"


def test_generate_answer():
    model, client = generator()
    answer, refs = model.generate_answer("query", [{"text": "Context A", "metadata": {"source": "docA", "page": 2}}])
    assert answer == "This is the answer [1]."
    assert refs[0]["metadata"] == {"source": "docA", "page": 2}
    assert client.generate.call_args.kwargs["options"]["num_predict"] == 512


def test_empty_context_never_calls_model():
    model, client = generator()
    assert model.generate_answer("question", [])[1] == []
    client.generate.assert_not_called()


@pytest.mark.parametrize("answer", ["Unsupported claim [99].", "Claim without citations.", "Unsupported claim [0]."])
def test_unverifiable_answers_do_not_get_fabricated_references(answer):
    model, _ = generator(answer)
    result, refs = model.generate_answer("query", [{"text": "Context", "metadata": {"source": "docA"}}])
    assert refs == []
    assert result != answer


@pytest.mark.parametrize("result", [None, ""])
def test_model_failures_raise_service_error(result):
    model, client = generator()
    if result is None:
        client.generate.side_effect = ConnectionError("offline")
    else:
        client.generate.return_value = {"response": result}
    with pytest.raises(ModelUnavailableError):
        model.generate_answer("query", [{"text": "Context", "metadata": {"source": "docA"}}])


def test_context_is_bounded_and_citations_only_include_visible_evidence():
    model, client = generator()
    model.context_tokens = 2048
    chunks = [{"text": "Long evidence. " * 1000, "metadata": {"source": f"doc{i}"}} for i in range(15)]
    prompt, selected = model._prepare_context("query", chunks)
    assert num_tokens_from_string(prompt) <= model.context_tokens - 1024
    assert len(selected) == 1
    model.generate_answer("query", chunks)
    assert client.generate.call_args.kwargs["options"]["num_ctx"] == 2048


def test_condensation_failure_keeps_original_question():
    model, client = generator()
    client.generate.side_effect = ConnectionError("offline")
    assert model.condense_query("original", [{"role": "user", "content": "history"}]) == "original"
