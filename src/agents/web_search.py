import logging
from typing import List, Dict, Any
from ddgs import DDGS

from src.errors import WebSearchUnavailableError

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
            with DDGS(timeout=15) as ddgs:
                results = list(ddgs.text(query, max_results=self.max_results, backend="duckduckgo"))
                
            formatted_chunks = []
            for item in results:
                if not item.get("body", "").strip() or not item.get("href", "").startswith(("https://", "http://")):
                    continue
                formatted_chunks.append({
                    "text": item.get('body', ''),
                    "metadata": {
                        "source": item.get('href', 'Web Search'),
                        "title": item.get('title', 'Unknown Title')
                    }
                })
            return formatted_chunks
        except Exception as e:
            logging.getLogger(__name__).warning("Web search unavailable (%s).", type(e).__name__)
            raise WebSearchUnavailableError("Web search could not return usable results.") from e
