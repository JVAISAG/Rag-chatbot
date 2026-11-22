"""Retrieval-only benchmark, using an isolated temporary database by default."""

import argparse
from contextlib import contextmanager
import gc
from itertools import zip_longest
import json
import math
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline import RAGPipeline


def load_eval_set(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


@contextmanager
def temporary_index():
    directory = tempfile.TemporaryDirectory(prefix="rag-evaluation-")
    try:
        yield directory.name
    finally:
        # Chroma may release its final Windows file handles asynchronously.
        # Retry only permission failures, within the directory tempfile created.
        target = Path(directory.name).resolve()
        if not target.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not target.name.startswith("rag-evaluation-"):
            raise RuntimeError("Unexpected temporary index directory.")
        for attempt in range(6):
            try:
                directory.cleanup()
                break
            except PermissionError:
                if attempt == 5:
                    raise
                gc.collect()
                time.sleep(min(0.1 * 2 ** attempt, 1))


def calculate_mrr(rankings):
    return sum(1 / rank if rank > 0 else 0 for rank in rankings) / len(rankings) if rankings else 0.0


def calculate_recall_at_k(rankings, k):
    # Each question has one relevant document: recall equals document hit rate.
    return sum(0 < rank <= k for rank in rankings) / len(rankings) if rankings else 0.0


def calculate_ndcg_at_k(rankings, k):
    return sum(1 / math.log2(rank + 1) if 0 < rank <= k else 0 for rank in rankings) / len(rankings) if rankings else 0.0


def get_rank_of_expected_source(results, expected_source):
    for rank, result in enumerate(results, 1):
        if result.get("metadata", {}).get("source", "").casefold() == expected_source.casefold():
            return rank
    return 0


def retrieve(pipeline, query, mode, k):
    if mode == "dense":
        return pipeline.dense_retriever.retrieve(query, top_k=k)
    if mode == "bm25":
        return pipeline.sparse_retriever.retrieve(query, top_k=k)
    if mode in {"hybrid_rrf", "hybrid_rrf_rerank"}:
        return pipeline.hybrid_retriever.retrieve(query, top_k=k, use_reranking=mode.endswith("_rerank"))
    if mode != "hybrid":
        raise ValueError(f"Unknown retrieval mode: {mode}")
    dense = pipeline.dense_retriever.retrieve(query, top_k=k)
    sparse = pipeline.sparse_retriever.retrieve(query, top_k=k)
    results, seen = [], set()
    for pair in zip_longest(dense, sparse):
        for item in pair:
            if item is not None and item["id"] not in seen:
                seen.add(item["id"])
                results.append(item)
    return results[:k]


def run_evaluation(eval_set, pipeline, mode, k=5):
    if k <= 0 or not eval_set:
        raise ValueError("Evaluation requires questions and a positive k.")
    rankings, durations = [], []
    for item in eval_set:
        started = perf_counter()
        results = retrieve(pipeline, item["question"], mode, k)
        durations.append(perf_counter() - started)
        rankings.append(get_rank_of_expected_source(results, item["expected_source"]))
    return {
        f"Recall@{k}": calculate_recall_at_k(rankings, k),
        f"MRR@{k}": calculate_mrr(rankings), f"NDCG@{k}": calculate_ndcg_at_k(rankings, k),
        "mean_latency_seconds": sum(durations) / len(durations),
    }


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=root / "fixtures")
    parser.add_argument("--eval-set", type=Path, default=root / "demo_set.json")
    parser.add_argument("--output", type=Path, default=root.parent / "docs" / "EVALUATION.md")
    parser.add_argument("--reranker", action="store_true")
    parser.add_argument("--k", type=int, default=1)
    args = parser.parse_args()
    questions = load_eval_set(args.eval_set)
    modes = ["dense", "bm25", "hybrid", "hybrid_rrf"]
    if args.reranker:
        modes.append("hybrid_rrf_rerank")
    results = {}
    # Benchmarking must never overwrite or mix with the user's document index.
    with temporary_index() as temporary, RAGPipeline(data_dir=str(args.data_dir), db_path=temporary) as pipeline:
        pipeline.build_index()
        sources = {item["name"].casefold() for item in pipeline.list_files()}
        if not questions or any(item["expected_source"].casefold() not in sources for item in questions):
            raise ValueError("Every expected source must exist in the evaluation corpus.")
        for mode in modes:
            print(f"Evaluating {mode}...", flush=True)
            results[mode] = run_evaluation(questions, pipeline, mode, args.k)
    k = args.k
    lines = [
        "# RAG evaluation report", "",
        f"Measured over {len(questions)} questions from `{args.eval_set.name}` with an isolated index.", "",
        "Embedding model: `all-MiniLM-L6-v2` (CPU). Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU).", "",
        f"| Method | Recall@{k} | MRR@{k} | nDCG@{k} | Mean retrieval seconds |",
        "|---|---:|---:|---:|---:|",
    ]
    for mode, result in results.items():
        lines.append(f"| {mode} | {result[f'Recall@{k}']:.3f} | {result[f'MRR@{k}']:.3f} | {result[f'NDCG@{k}']:.3f} | {result['mean_latency_seconds']:.3f} |")
    if not args.reranker:
        lines.extend(["", "Reranking was not evaluated. Enable it with `--reranker`; no timeout is inferred."])
    lines.extend(["", "One expected document is labelled per question; recall is therefore document hit rate. "
                  "MRR is truncated at k. This small synthetic corpus is a smoke benchmark, not a held-out quality claim. "
                  "Generation faithfulness, citation support, unanswerable questions, and production latency are not evaluated here.", ""])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()
