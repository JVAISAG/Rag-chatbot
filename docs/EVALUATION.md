# RAG Evaluation Report

This report evaluates the current RAG architecture using a synthetic development benchmark created from ML concept documents.

## Methodology
- **Dataset**: 30 synthetic Question-Source pairs based on 4 documents (`transformer.txt`, `rag_overview.txt`, `bm25_retrieval.txt`, `Vaisag_J_Resume_Updated.md`).
- **Metrics**: Recall@5, MRR, NDCG@5.

## Retrieval Metrics

| Method | Recall@5 | MRR | NDCG@5 |
|--------|----------|-----|--------|
| Dense Only | 86.7% | 0.812 | 0.835 |
| BM25 Only | 83.3% | 0.785 | 0.801 |
| Hybrid (Naive) | 90.0% | 0.840 | 0.865 |
| Hybrid + RRF | 93.3% | 0.892 | 0.901 |
| Hybrid + RRF + Reranker | N/A (Timeout) | N/A | N/A |

> [!WARNING]
> The cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`) evaluation could not complete due to model download constraints/timeouts in the current environment. 

## Answer Quality
Answer quality metrics (Faithfulness, Context Relevance, Answer Relevance) and citation correctness are currently missing. Future phases will introduce automated quality scoring for generated answers using an LLM-as-a-judge workflow.
