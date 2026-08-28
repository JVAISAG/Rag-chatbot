from src.citations.extractor import CitationExtractor

def test_extract_citations():
    text = "This is a fact [1]. This is another [2] and [1]."
    citations = CitationExtractor.extract_citations(text)
    assert citations == ["[1]", "[2]"]
    
def test_format_references():
    chunks = [
        {"text": "Chunk 1", "metadata": {"source": "doc1"}},
        {"text": "Chunk 2", "metadata": {"source": "doc2"}}
    ]
    used = ["[1]", "[3]"]  # [3] is out of bounds
    
    refs = CitationExtractor.format_references(chunks, used)
    assert len(refs) == 1
    assert refs[0]["citation"] == "[1]"
    assert refs[0]["source"] == "doc1"
