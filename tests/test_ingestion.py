from docx import Document
from pypdf import PdfWriter
import pytest

from src.errors import DocumentError
from src.ingestion.document_loader import load_document


def test_docx_includes_table_contents(tmp_path):
    document = Document()
    document.add_paragraph("Body text")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Requirement"
    table.cell(0, 1).text = "Email login"
    path = tmp_path / "sample.docx"
    document.save(path)
    text = load_document(str(path))[0]["text"]
    assert "Body text" in text
    assert "Email login" in text


def test_utf8_bom_is_supported(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text("Hello café", encoding="utf-8-sig")
    assert load_document(str(path))[0]["text"] == "Hello café"


@pytest.mark.parametrize("name,content", [("sample.txt", b"   "), ("sample.pdf", b"broken"), ("sample.docx", b"broken")])
def test_unreadable_documents_are_rejected(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(DocumentError):
        load_document(str(path))


def test_scanned_or_blank_pdf_reports_no_readable_text(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    path = tmp_path / "blank.pdf"
    writer.write(path)
    with pytest.raises(DocumentError, match="OCR"):
        load_document(str(path))
