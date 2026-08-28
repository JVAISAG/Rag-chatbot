import os
from typing import List, Dict, Any
from pypdf import PdfReader
from docx import Document

def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF file."""
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n\n"
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
    return text.strip()

def extract_text_from_docx(file_path: str) -> str:
    """Extract text from a DOCX file."""
    text = ""
    try:
        doc = Document(file_path)
        for para in doc.paragraphs:
            if para.text:
                text += para.text + "\n"
    except Exception as e:
        print(f"Error reading DOCX {file_path}: {e}")
    return text.strip()

def extract_text_from_txt(file_path: str) -> str:
    """Extract text from a TXT or MD file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        print(f"Error reading text file {file_path}: {e}")
        return ""

def load_documents(data_dir: str) -> List[Dict[str, Any]]:
    """
    Load all supported documents from the data directory.
    Returns a list of dicts: {'text': str, 'source': str, 'metadata': dict}
    """
    documents = []
    
    if not os.path.exists(data_dir):
        print(f"Directory {data_dir} does not exist.")
        return documents

    for root, _, files in os.walk(data_dir):
        for file in files:
            file_path = os.path.join(root, file)
            ext = os.path.splitext(file)[1].lower()
            
            text = ""
            if ext == ".pdf":
                text = extract_text_from_pdf(file_path)
            elif ext == ".docx":
                text = extract_text_from_docx(file_path)
            elif ext in [".txt", ".md"]:
                text = extract_text_from_txt(file_path)
            else:
                continue # Unsupported file type
                
            if text:
                documents.append({
                    "text": text,
                    "source": file,
                    "metadata": {
                        "filepath": file_path,
                        "extension": ext
                    }
                })
                
    return documents
