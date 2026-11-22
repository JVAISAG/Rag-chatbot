import re
from typing import List, Dict, Any

class CitationExtractor:
    """Extracts and formats citations from generated text."""
    
    @staticmethod
    def extract_citations(text: str) -> List[str]:
        """
        Find all citation markers like [1], [2] in the text.
        """
        citations = re.findall(r'\[\d+\]', text)
        # Deduplicate and sort
        unique_citations = sorted(set(citations), key=lambda value: int(value[1:-1]))
        return unique_citations

    @staticmethod
    def format_references(retrieved_chunks: List[Dict[str, Any]], used_citations: List[str]) -> List[Dict[str, Any]]:
        """
        Map used citations to actual document metadata for UI display.
        """
        references = []
        for citation in used_citations:
            try:
                # Extract number from [1]
                idx = int(citation.strip('[]')) - 1 
                if 0 <= idx < len(retrieved_chunks):
                    chunk = retrieved_chunks[idx]
                    references.append({
                        "citation": citation,
                        "source": chunk['metadata'].get('source', 'Unknown'),
                        "metadata": {key: value for key, value in chunk["metadata"].items() if key != "filepath"},
                        "text_snippet": chunk['text'][:300] + ("..." if len(chunk['text']) > 300 else "")
                    })
            except ValueError:
                continue
        return references
