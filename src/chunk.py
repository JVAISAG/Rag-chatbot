import tiktoken
from typing import List, Dict, Any

def num_tokens_from_string(string: str, encoding_name: str = "cl100k_base") -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding(encoding_name)
    num_tokens = len(encoding.encode(string))
    return num_tokens

def chunk_text(text: str, source: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Splits text recursively by paragraphs, then sentences if necessary,
    based on token counts.
    """
    chunks = []
    
    # Very basic recursive splitting logic:
    # 1. Split by double newline (paragraphs)
    paragraphs = text.split('\n\n')
    
    current_chunk_text = ""
    current_chunk_tokens = 0
    chunk_index = 0
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        para_tokens = num_tokens_from_string(para)
        
        # If a single paragraph is too big, split it by sentence
        if para_tokens > chunk_size:
            sentences = para.replace('. ', '.\n').split('\n')
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                sentence_tokens = num_tokens_from_string(sentence)
                if current_chunk_tokens + sentence_tokens > chunk_size and current_chunk_text:
                    # Save current chunk
                    chunks.append({
                        "text": current_chunk_text.strip(),
                        "metadata": {
                            "source": source,
                            "chunk_index": chunk_index
                        }
                    })
                    chunk_index += 1
                    
                    # Overlap handling (simplistic: taking last N tokens roughly via string split or sentence overlap)
                    # For a robust overlap, we could keep a rolling buffer of sentences.
                    # Here we just start fresh with the new sentence.
                    current_chunk_text = sentence + " "
                    current_chunk_tokens = sentence_tokens
                else:
                    current_chunk_text += sentence + " "
                    current_chunk_tokens += sentence_tokens
        else:
            if current_chunk_tokens + para_tokens > chunk_size and current_chunk_text:
                chunks.append({
                    "text": current_chunk_text.strip(),
                    "metadata": {
                        "source": source,
                        "chunk_index": chunk_index
                    }
                })
                chunk_index += 1
                
                # Naive overlap: keep the last paragraph if it fits in overlap
                # (A better implementation would use LangChain's RecursiveCharacterTextSplitter with length_function=num_tokens_from_string)
                current_chunk_text = para + "\n\n"
                current_chunk_tokens = para_tokens
            else:
                current_chunk_text += para + "\n\n"
                current_chunk_tokens += para_tokens
                
    if current_chunk_text.strip():
        chunks.append({
            "text": current_chunk_text.strip(),
            "metadata": {
                "source": source,
                "chunk_index": chunk_index
            }
        })
        
    return chunks

def process_documents(documents: List[Dict[str, Any]], chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """Process a list of documents into chunks."""
    all_chunks = []
    for doc in documents:
        text = doc["text"]
        source = doc["source"]
        doc_chunks = chunk_text(text, source, chunk_size, overlap)
        
        # Merge existing metadata from doc with chunk metadata
        for chunk in doc_chunks:
            merged_meta = doc["metadata"].copy()
            merged_meta.update(chunk["metadata"])
            chunk["metadata"] = merged_meta
            
        all_chunks.extend(doc_chunks)
    return all_chunks

if __name__ == "__main__":
    # Quick test
    sample_doc = {
        "text": "This is a test document. " * 50 + "\n\n" + "Here is a new paragraph. " * 50,
        "source": "test.txt",
        "metadata": {"filepath": "/path/to/test.txt"}
    }
    chunks = process_documents([sample_doc], chunk_size=50)
    print(f"Generated {len(chunks)} chunks.")
    for i, c in enumerate(chunks[:2]):
        print(f"Chunk {i} tokens: {num_tokens_from_string(c['text'])}")
