from unittest.mock import patch
from src.agents.web_search import WebSearchTool

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
