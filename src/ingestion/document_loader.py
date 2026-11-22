import hashlib
from pathlib import Path
from typing import Any, Dict, List
from zipfile import ZipFile

from pypdf import PdfReader
from docx import Document

from src.errors import DocumentError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def load_document(file_path: str, source: str = None) -> List[Dict[str, Any]]:
    path = Path(file_path).resolve()
    extension = path.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentError("Unsupported document type.")
    try:
        metadata = {
            "filepath": str(path), "extension": extension,
            "file_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        parts = []
        if extension == ".pdf":
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise DocumentError("Encrypted PDFs must be unlocked before uploading.")
            parts = [(page.extract_text() or "", {"page": number}) for number, page in enumerate(reader.pages, 1)]
        elif extension == ".docx":
            with ZipFile(path) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise DocumentError("The expanded document exceeds the 50 MB processing limit.")
            document = Document(str(path))
            paragraphs = [para.text for para in document.paragraphs if para.text.strip()]
            for table in document.tables:
                paragraphs.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
            parts = [("\n\n".join(paragraphs), {})]
        else:
            parts = [(path.read_text(encoding="utf-8-sig"), {})]
        documents = [
            {"text": text.strip(), "source": source or path.name, "metadata": {**metadata, **extra}}
            for text, extra in parts if text.strip()
        ]
        if not documents:
            raise DocumentError("No readable text found. Scanned PDFs need OCR before uploading.")
        return documents
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("Could not read the document. Check its format and contents.") from exc


def _extract_document_text(file_path: str) -> str:
    return "\n\n".join(doc["text"] for doc in load_document(file_path))


def extract_text_from_pdf(file_path: str) -> str:
    return _extract_document_text(file_path)


def extract_text_from_docx(file_path: str) -> str:
    return _extract_document_text(file_path)


def extract_text_from_txt(file_path: str) -> str:
    return _extract_document_text(file_path)


def load_documents(data_dir: str, source_overrides=None) -> List[Dict[str, Any]]:
    root = Path(data_dir).resolve()
    documents = []
    if not root.exists():
        return documents
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if not path.resolve().is_relative_to(root):
            raise DocumentError("Document paths must stay inside the data directory.")
        source = (source_overrides or {}).get(str(path.resolve()), path.relative_to(root).as_posix())
        documents.extend(load_document(str(path), source))
    return documents
