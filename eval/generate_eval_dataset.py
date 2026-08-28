import json
import os

eval_data = [
    {"question": "Who developed the Transformer architecture?", "expected_answer": "Google Researchers", "expected_source": "transformer.txt"},
    {"question": "What is the name of the 2017 paper that introduced the Transformer?", "expected_answer": "Attention Is All You Need", "expected_source": "transformer.txt"},
    {"question": "Does the Transformer use recurrence or convolutions?", "expected_answer": "No, it dispenses with them entirely.", "expected_source": "transformer.txt"},
    {"question": "What are the two main components of the Transformer architecture?", "expected_answer": "An encoder and a decoder.", "expected_source": "transformer.txt"},
    {"question": "What is the purpose of Multi-Head Attention?", "expected_answer": "It linearly projects the queries, keys, and values h times with different learned linear projections.", "expected_source": "transformer.txt"},
    {"question": "What does BERT stand for?", "expected_answer": "Bidirectional Encoder Representations from Transformers", "expected_source": "transformer.txt"},
    {"question": "Why is positional encoding added to the Transformer?", "expected_answer": "To inject information about the relative or absolute position of the tokens.", "expected_source": "transformer.txt"},
    {"question": "Where is positional encoding added in the Transformer?", "expected_answer": "At the bottoms of the encoder and decoder stacks.", "expected_source": "transformer.txt"},

    {"question": "What does RAG stand for?", "expected_answer": "Retrieval-Augmented Generation", "expected_source": "rag_overview.txt"},
    {"question": "How does RAG augment a Large Language Model?", "expected_answer": "By adding an information retrieval system that provides grounding data.", "expected_source": "rag_overview.txt"},
    {"question": "What happens to the external corpus of documents in a RAG system?", "expected_answer": "They are chunked into smaller segments and encoded into dense vectors.", "expected_source": "rag_overview.txt"},
    {"question": "Name three examples of vector databases mentioned in the text.", "expected_answer": "ChromaDB, FAISS, or Pinecone.", "expected_source": "rag_overview.txt"},
    {"question": "How are the most similar chunks usually found in a vector database?", "expected_answer": "Using cosine similarity or dot product.", "expected_source": "rag_overview.txt"},
    {"question": "What is a major benefit of using RAG regarding hallucinations?", "expected_answer": "It significantly reduces hallucination because the model bases its answer on retrieved context.", "expected_source": "rag_overview.txt"},
    {"question": "Does RAG require expensive fine-tuning to answer questions about recent data?", "expected_answer": "No, it does not.", "expected_source": "rag_overview.txt"},
    {"question": "What does RRF stand for in the context of advanced RAG techniques?", "expected_answer": "Reciprocal Rank Fusion", "expected_source": "rag_overview.txt"},
    
    {"question": "What does BM25 stand for?", "expected_answer": "Best Matching 25", "expected_source": "bm25_retrieval.txt"},
    {"question": "Who were the researchers that helped develop the probabilistic retrieval framework in the 70s and 80s?", "expected_answer": "Stephen Robertson and Karen Spärck Jones.", "expected_source": "bm25_retrieval.txt"},
    {"question": "Is BM25 a dense or sparse retrieval method?", "expected_answer": "It is a sparse retrieval method.", "expected_source": "bm25_retrieval.txt"},
    {"question": "What two metrics does the BM25 scoring function take into account?", "expected_answer": "Term Frequency (TF) and Inverse Document Frequency (IDF).", "expected_source": "bm25_retrieval.txt"},
    {"question": "What is term frequency saturation in BM25?", "expected_answer": "It means that the impact of a term appearing multiple times in a document tapers off.", "expected_source": "bm25_retrieval.txt"},
    {"question": "Which hyperparameter controls term frequency saturation in BM25?", "expected_answer": "The hyperparameter k1.", "expected_source": "bm25_retrieval.txt"},
    {"question": "What is the typical range for the hyperparameter k1 in BM25?", "expected_answer": "Between 1.2 and 2.0", "expected_source": "bm25_retrieval.txt"},
    {"question": "Why does BM25 penalize long documents?", "expected_answer": "To ensure they do not unfairly rank higher just because they have more words.", "expected_source": "bm25_retrieval.txt"},
    {"question": "Which hyperparameter controls document length normalization in BM25?", "expected_answer": "The hyperparameter b.", "expected_source": "bm25_retrieval.txt"},
    {"question": "What is the typical value for the hyperparameter b in BM25?", "expected_answer": "Usually set to 0.75.", "expected_source": "bm25_retrieval.txt"},
    {"question": "How is BM25 used alongside dense retrieval?", "expected_answer": "In hybrid search architectures, where results are fused using techniques like RRF.", "expected_source": "bm25_retrieval.txt"},
    
    {"question": "What is the title of the resume document?", "expected_answer": "Vaisag_J_Resume_Updated", "expected_source": "Vaisag_J_Resume_Updated.md"},
    {"question": "Whose resume is stored in the data folder?", "expected_answer": "Vaisag J", "expected_source": "Vaisag_J_Resume_Updated.md"},
    {"question": "What is the main topic of the Attention Is All You Need paper?", "expected_answer": "The Transformer architecture.", "expected_source": "transformer.txt"}
]

if __name__ == "__main__":
    filepath = os.path.join(os.path.dirname(__file__), "eval_set.json")
    with open(filepath, 'w') as f:
        json.dump(eval_data, f, indent=2)
    print(f"Generated {len(eval_data)} questions at {filepath}")
