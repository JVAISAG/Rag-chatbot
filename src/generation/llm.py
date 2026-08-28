import ollama
from typing import List, Dict, Any, Tuple
from src.citations.extractor import CitationExtractor

class LLMGenerator:
    def __init__(self, model_name: str = "llama3.2"):
        self.model_name = model_name

    def build_prompt(self, query: str, context_chunks: List[Dict[str, Any]]) -> str:
        """
        Build a prompt combining context and user query.
        Instructs the model to use [1], [2] citations.
        """
        context_text = ""
        for i, chunk in enumerate(context_chunks):
            context_text += f"Document [{i+1}] (Source: {chunk['metadata'].get('source', 'Unknown')}):\n{chunk['text']}\n\n"
            
        prompt = f"""You are an intelligent, helpful AI assistant. 
Use the following pieces of retrieved context to answer the user's question. 
When you use information from a piece of context, you MUST cite it using the corresponding document number in square brackets, e.g., [1] or [2].
If you don't know the answer based on the context, just say that you don't know, don't try to make up an answer.

Context:
{context_text}

User Question: {query}

Answer (with citations):"""
        return prompt

    def generate_answer(self, query: str, context_chunks: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer using Ollama and extract formatted references.
        """
        if not context_chunks:
            return "I could not find any relevant information to answer your question.", []
            
        prompt = self.build_prompt(query, context_chunks)
        
        try:
            response = ollama.generate(model=self.model_name, prompt=prompt)
            answer_text = response.get('response', '')
            
            # Extract citations
            used_citations = CitationExtractor.extract_citations(answer_text)
            references = CitationExtractor.format_references(context_chunks, used_citations)
            
            return answer_text, references
            
        except Exception as e:
            print(f"Error generating answer from Ollama: {e}")
            return f"Error connecting to LLM ({self.model_name}). Make sure Ollama is running.", []

    def condense_query(self, user_query: str, chat_history: List[Dict[str, str]]) -> str:
        """
        Rewrite a follow-up query to be a standalone query based on chat history.
        """
        if not chat_history:
            return user_query
            
        # Format history
        history_text = ""
        for msg in chat_history[-3:]: # Only use last 3 interactions to save context
            role = "User" if msg["role"] == "user" else "Assistant"
            history_text += f"{role}: {msg['content']}\n"
            
        prompt = f"""Given the following conversation history and a follow-up user question, rephrase the follow-up question to be a standalone question.
If the follow-up question is already standalone or doesn't refer to the history, return it exactly as is.
DO NOT answer the question, just return the standalone question.

Chat History:
{history_text}

Follow-up Question: {user_query}

Standalone Question:"""

        try:
            response = ollama.generate(model=self.model_name, prompt=prompt)
            condensed = response.get('response', '').strip()
            # Basic cleanup in case model gets chatty
            if '\n' in condensed:
                condensed = condensed.split('\n')[0]
            if condensed.lower().startswith('standalone question:'):
                condensed = condensed[len('standalone question:'):].strip()
            return condensed if condensed else user_query
        except Exception as e:
            print(f"Query condensation failed: {e}")
            return user_query
