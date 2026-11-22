from src.chunking.text_splitter import chunk_text, num_tokens_from_string, process_documents
import pytest

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
    chunks = process_documents(docs, chunk_size=20, overlap=5)
    assert len(chunks) > 1
    assert chunks[0]["metadata"]["author"] == "John"
    assert chunks[0]["metadata"]["source"] == "doc1.txt"


@pytest.mark.parametrize("text", [
    " ".join(f"word{i}" for i in range(300)),
    "".join(f"{i:04d}x" for i in range(200)),
    " ".join(f"中文🙂 café മലയാളം {i}" for i in range(70)),
    " ".join(f"<|endoftext|>{i}" for i in range(100)),
], ids=["words", "unbroken", "unicode", "special-markers"])
def test_chunks_respect_token_limit_and_preserve_content(text):
    chunks = chunk_text(text, "example.txt", chunk_size=32, overlap=6)
    covered = set()
    previous_start = -1
    for chunk in chunks:
        assert num_tokens_from_string(chunk["text"]) <= 32
        assert "\ufffd" not in chunk["text"]
        start = text.find(chunk["text"], previous_start + 1)
        assert start >= 0
        covered.update(range(start, start + len(chunk["text"])))
        previous_start = start
    assert all(index in covered for index, character in enumerate(text) if not character.isspace())


def test_overlap_is_actually_present():
    text = " ".join(f"token{i}" for i in range(80))
    chunks = chunk_text(text, "example.txt", chunk_size=32, overlap=8)
    for left, right in zip(chunks, chunks[1:]):
        suffixes = [left["text"][-length:] for length in range(1, len(left["text"])) if right["text"].startswith(left["text"][-length:])]
        assert suffixes
        assert num_tokens_from_string(max(suffixes, key=len)) <= 8


@pytest.mark.parametrize("size,overlap", [(0, 0), (10, -1), (10, 10), (10, 20)])
def test_invalid_chunk_parameters(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("text", "example.txt", size, overlap)


def test_pdf_pages_have_unique_chunk_indices():
    docs = [{"text": f"Page {page}", "source": "file.pdf", "metadata": {"page": page}} for page in (1, 2)]
    chunks = process_documents(docs)
    assert [chunk["metadata"]["chunk_index"] for chunk in chunks] == [0, 1]
    assert [chunk["metadata"]["page"] for chunk in chunks] == [1, 2]
