from unittest.mock import patch
from src.agents.web_search import WebSearchTool
from src.errors import WebSearchUnavailableError
import pytest

@patch('src.agents.web_search.DDGS')
def test_web_search_tool(mock_ddgs):
    # Setup mock
    mock_instance = mock_ddgs.return_value.__enter__.return_value
    mock_instance.text.return_value = [
        {"title": "Python 3.12", "href": "https://python.org", "body": "Latest release is 3.12"}
    ]
    
    tool = WebSearchTool()
    results = tool.search("latest python version")
    
    assert len(results) == 1
    assert results[0]["text"] == "Latest release is 3.12"
    assert results[0]["metadata"]["source"] == "https://python.org"
    mock_instance.text.assert_called_once_with("latest python version", max_results=5, backend="duckduckgo")


@patch('src.agents.web_search.DDGS', side_effect=RuntimeError("provider offline"))
def test_provider_failure_is_not_an_empty_success(mock_ddgs):
    with pytest.raises(WebSearchUnavailableError):
        WebSearchTool().search("query")


@patch('src.agents.web_search.DDGS')
def test_empty_snippets_and_invalid_urls_are_not_evidence(mock_ddgs):
    instance = mock_ddgs.return_value.__enter__.return_value
    instance.text.return_value = [{"body": "", "href": "https://example.com"}, {"body": "text", "href": "javascript:bad"}]
    assert WebSearchTool().search("query") == []
