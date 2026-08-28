from unittest.mock import patch
from src.generation.llm import LLMGenerator

@patch('ollama.generate')
def test_condense_query(mock_generate):
    mock_generate.return_value = {"response": "Standalone Question: What is a transformer?"}
    
    generator = LLMGenerator()
    history = [{"role": "user", "content": "Tell me about it."}]
    
    result = generator.condense_query("What is it?", history)
    
    assert result == "What is a transformer?"
    assert mock_generate.called

@patch('ollama.generate')
def test_generate_answer(mock_generate):
    mock_generate.return_value = {"response": "This is the answer [1]."}
    
    generator = LLMGenerator()
    chunks = [{"text": "Context A", "metadata": {"source": "docA"}}]
    
    answer, refs = generator.generate_answer("query", chunks)
    
    assert "This is the answer" in answer
    assert len(refs) == 1
    assert refs[0]["citation"] == "[1]"
