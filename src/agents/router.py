import ollama
from typing import Dict, Any

class QueryRouter:
    """
    Classifies a user query into one of the predefined intents:
    - SMALL_TALK: Casual conversation, greetings, etc.
    - SUMMARIZATION: Requests to summarize documents or large concepts.
    - DIRECT_KNOWLEDGE: Specific questions requiring document retrieval (default).
    """
    def __init__(self, model_name: str = "llama3.2"):
        self.model_name = model_name

    def route_query(self, query: str) -> str:
        """
        Determine the intent of the query using the LLM.
        """
        prompt = f"""You are a query classifier for a RAG system.
Classify the user's query into EXACTLY ONE of these four categories:
1. SMALL_TALK (e.g., "hello", "how are you", "who made you")
2. SUMMARIZATION (e.g., "summarize my documents", "give me a summary of everything")
3. WEB_SEARCH (e.g., "search the web for X", "what is the latest news on Y", "look up Z online")
4. DIRECT_KNOWLEDGE (e.g., "what is X", "how does Y work", "explain Z based on documents")

Only output the category name and nothing else.

Query: "{query}"
Category:"""
        try:
            response = ollama.generate(model=self.model_name, prompt=prompt)
            classification = response.get('response', '').strip().upper()
            
            # Defensive checks to ensure valid enum string
            if "SMALL_TALK" in classification:
                return "SMALL_TALK"
            elif "SUMMARIZATION" in classification:
                return "SUMMARIZATION"
            elif "WEB_SEARCH" in classification:
                return "WEB_SEARCH"
            else:
                return "DIRECT_KNOWLEDGE"
        except Exception as e:
            print(f"Router error: {e}")
            return "DIRECT_KNOWLEDGE" # Fallback
