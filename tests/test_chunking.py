from src.chunking.text_splitter import chunk_text, num_tokens_from_string, process_documents

def test_num_tokens_from_string():
    tokens = num_tokens_from_string("hello world")
    assert tokens > 0

def test_chunk_text():
    text = "This is a sentence. " * 50  # Make it long enough
    chunks = chunk_text(text, source="test.txt", chunk_size=20, overlap=5)
    assert len(chunks) > 1
    assert "metadata" in chunks[0]
    assert chunks[0]["metadata"]["source"] == "test.txt"

def test_process_documents():
    docs = [{"text": "Hello world. " * 50, "source": "doc1.txt", "metadata": {"author": "John"}}]
    chunks = process_documents(docs, chunk_size=20)
    assert len(chunks) > 1
    assert chunks[0]["metadata"]["author"] == "John"
    assert chunks[0]["metadata"]["source"] == "doc1.txt"
