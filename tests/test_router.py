from unittest.mock import patch
from src.agents.router import QueryRouter

@patch('ollama.generate')
def test_query_router_small_talk(mock_generate):
    mock_generate.return_value = {"response": "SMALL_TALK"}
    router = QueryRouter()
    intent = router.route_query("Hi there, how are you?")
    assert intent == "SMALL_TALK"
    assert mock_generate.called

@patch('ollama.generate')
def test_query_router_summarization(mock_generate):
    mock_generate.return_value = {"response": " SUMMARIZATION "}
    router = QueryRouter()
    intent = router.route_query("Please summarize the documents for me.")
    assert intent == "SUMMARIZATION"

@patch('ollama.generate')
def test_query_router_direct_knowledge(mock_generate):
    mock_generate.return_value = {"response": "DIRECT_KNOWLEDGE"}
    router = QueryRouter()
    intent = router.route_query("What is the main topic of document A?")
    assert intent == "DIRECT_KNOWLEDGE"

@patch('ollama.generate')
def test_query_router_fallback(mock_generate):
    mock_generate.return_value = {"response": "I am not sure."}
    router = QueryRouter()
    intent = router.route_query("Some weird query")
    assert intent == "DIRECT_KNOWLEDGE" # Fallback behavior
