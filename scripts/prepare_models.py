"""Download caches once, before using the application offline."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chunking.text_splitter import get_encoding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", action="store_true", help="Prepare the document embedding model.")
    parser.add_argument("--reranker", action="store_true", help="Prepare the optional cross-encoder model.")
    args = parser.parse_args()
    get_encoding()
    print("Tokenizer ready.")
    if args.embeddings:
        from src.embeddings.models import get_embedding_model
        get_embedding_model()
        print("Embedding model ready.")
    if args.reranker:
        from src.retrieval.reranker import get_cross_encoder
        get_cross_encoder()
        print("Reranking model ready.")


if __name__ == "__main__":
    main()
