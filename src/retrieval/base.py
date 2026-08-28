from abc import ABC, abstractmethod
from typing import List, Dict, Any

class Retriever(ABC):
    """Abstract base class for all retrievers."""
    
    @abstractmethod
    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve chunks based on a query.
        Returns a list of dicts with keys 'id', 'text', 'metadata', 'score'.
        """
        pass
