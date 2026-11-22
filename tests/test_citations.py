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


def test_citations_sort_numerically():
    assert CitationExtractor.extract_citations("[10] [2] [1] [2]") == ["[1]", "[2]", "[10]"]


def test_reference_metadata_omits_local_filepath():
    refs = CitationExtractor.format_references([
        {"text": "Short quote", "metadata": {"source": "notes.pdf", "page": 3, "filepath": "private/location"}}
    ], ["[1]"])
    assert refs[0]["metadata"] == {"source": "notes.pdf", "page": 3}
    assert refs[0]["text_snippet"] == "Short quote"
