"""Unicode-safe chunks with an enforced token limit and real overlap."""

from functools import lru_cache
import os
from pathlib import Path
import re
from typing import Any, Dict, List

import tiktoken

from src.errors import ModelUnavailableError

os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).resolve().parents[2] / ".cache" / "tiktoken"))


@lru_cache(maxsize=4)
def get_encoding(encoding_name: str = "cl100k_base"):
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception as exc:
        raise ModelUnavailableError("Tokenizer unavailable. Run python scripts/prepare_models.py while online first.") from exc


def num_tokens_from_string(string: str, encoding_name: str = "cl100k_base") -> int:
    return len(get_encoding(encoding_name).encode(string, disallowed_special=()))


def _prefix_length(text: str, budget: int, token_counter=num_tokens_from_string) -> int:
    # Work on characters, never decoded partial UTF-8 tokens.
    low, high = 0, min(len(text), budget * 16)
    while low < high:
        mid = (low + high + 1) // 2
        if token_counter(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return low


def chunk_text(text: str, source: str, chunk_size: int = 500, overlap: int = 50, *, token_counter=None) -> List[Dict[str, Any]]:
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("Require chunk_size > 0 and 0 <= overlap < chunk_size.")
    chunks = []
    count_tokens = token_counter or num_tokens_from_string
    start = 0
    while start < len(text):
        remaining = text[start:]
        length = _prefix_length(remaining, chunk_size, count_tokens)
        if not length:
            raise ValueError("chunk_size is too small to encode a character in this document.")
        if length < len(remaining):
            boundaries = list(re.finditer(r"\n\s*\n|(?<=[.!?])\s+|\s+", remaining[:length]))
            preferred = [m.end() for m in boundaries if m.end() >= length // 2]
            if preferred and count_tokens(remaining[:preferred[-1]]) <= chunk_size:
                length = preferred[-1]
        end = start + length
        content = text[start:end]
        if content.strip():
            chunks.append({
                "text": content,
                "metadata": {"source": source, "chunk_index": len(chunks)},
            })
        if end == len(text):
            break
        suffix_length = 0
        if overlap:
            low, high = 0, len(content)
            while low < high:
                mid = (low + high + 1) // 2
                if count_tokens(content[-mid:]) <= overlap:
                    low = mid
                else:
                    high = mid - 1
            suffix_length = low
        start = max(start + 1, end - suffix_length)
    return chunks


def process_documents(documents: List[Dict[str, Any]], chunk_size: int = 500, overlap: int = 50, *, token_counter=None) -> List[Dict[str, Any]]:
    all_chunks = []
    source_indices = {}
    for doc in documents:
        source = doc["source"]
        for chunk in chunk_text(doc["text"], source, chunk_size, overlap, token_counter=token_counter):
            index = source_indices.get(source, 0)
            chunk["metadata"] = {
                **doc.get("metadata", {}), **chunk["metadata"], "chunk_index": index,
            }
            source_indices[source] = index + 1
            all_chunks.append(chunk)
    return all_chunks
