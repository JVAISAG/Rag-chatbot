from typing import List, Dict, Any
from duckduckgo_search import DDGS

class WebSearchTool:
    """
    Agentic tool to perform web searches when queries fall outside the local corpus.
    """
    def __init__(self, max_results: int = 5):
        self.max_results = max_results
        
    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Search the web using DuckDuckGo and format results to match chunk schema.
        """
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=self.max_results))
                
            formatted_chunks = []
            for item in results:
                formatted_chunks.append({
                    "text": item.get('body', ''),
                    "metadata": {
                        "source": item.get('href', 'Web Search'),
                        "title": item.get('title', 'Unknown Title')
                    }
                })
            return formatted_chunks
        except Exception as e:
            print(f"Web search failed: {e}")
            return []
