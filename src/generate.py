import ollama
from typing import List, Dict, Any, Tuple
import re

def build_prompt(question: str, chunks: List[Dict[str, Any]]) -> str:
    """Build the generation prompt with context chunks."""
    prompt = (
        "You are an intelligent assistant. Answer the question using ONLY the numbered sources below.\n"
        "Cite sources inline using brackets like [1], [2].\n"
        "If the answer isn't in the sources, say 'I cannot find the answer in the provided documents.'\n\n"
    )
    
    for i, chunk in enumerate(chunks, start=1):
        prompt += f"[{i}] {chunk['text']}\n\n"
        
    prompt += f"Question: {question}\nAnswer:"
    return prompt

def generate_answer(query: str, chunks: List[Dict[str, Any]], model: str = "llama3.2") -> Tuple[str, List[Dict[str, Any]]]:
    """
    Generate an answer using local Ollama model.
    Returns the answer text and a mapped list of used sources.
    """
    if not chunks:
        return "I don't have any relevant documents to answer that question.", []
        
    prompt = build_prompt(query, chunks)
    
    try:
        response = ollama.generate(model=model, prompt=prompt)
        answer = response['response'].strip()
        
        # Post-process: Attempt to map citations [1], [2] to actual source chunks
        cited_indices = set()
        # Find all [N] in the text
        citations = re.findall(r'\[(\d+)\]', answer)
        for c in citations:
            try:
                idx = int(c) - 1 # 0-indexed
                if 0 <= idx < len(chunks):
                    cited_indices.add(idx)
            except ValueError:
                pass
                
        # If model failed to cite properly but we provided chunks, we might want to just list all as 'potential sources'
        # But we'll trust the citations if present.
        used_sources = [chunks[i] for i in sorted(list(cited_indices))]
        if not used_sources and "I cannot find" not in answer:
            # Fallback: if the model answered but forgot to cite, list all top chunks as sources
            used_sources = chunks
            
        return answer, used_sources
        
    except Exception as e:
        print(f"Error generating answer: {e}")
        return "Sorry, I encountered an error while trying to generate an answer.", []
