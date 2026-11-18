import argparse
import json
import os
import time
from pathlib import Path
from statistics import mean
from typing import Any

from app.retrieval.hybrid import CorpusChunk, _bm25_scores
from evals.metrics import retrieval_metrics

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "datasets" / "incident_benchmark.json"


def _dense_scores(model: Any, query: str, texts: list[str]) -> list[tuple[int, float]]:
    vectors = model.encode([query, *texts], normalize_embeddings=True)
    scores = vectors[1:] @ vectors[0]
    return sorted(
        enumerate(float(score) for score in scores),
        key=lambda item: item[1],
        reverse=True,
    )


def _rank_case(
    method: str, query: str, corpus: list[dict[str, str]], model: Any
) -> list[str]:
    chunks = [
        CorpusChunk(
            source_id="benchmark",
            document_id=item["document_id"],
            chunk_id=item["document_id"],
            text=item["text"],
            metadata={"source": item["source"]},
        )
        for item in corpus
    ]
    sparse = _bm25_scores(query, chunks)
    dense = _dense_scores(model, query, [item["text"] for item in corpus])
    if method == "semantic":
        ranked = dense
    else:
        sparse_rank = {index: rank for rank, (index, _) in enumerate(sparse, 1)}
        dense_rank = {index: rank for rank, (index, _) in enumerate(dense, 1)}
        all_indexes = set(sparse_rank) | set(dense_rank)
        ranked = sorted(
            (
                (
                    index,
                    1 / (60 + sparse_rank[index]) * (index in sparse_rank)
                    + 1 / (60 + dense_rank[index]) * (index in dense_rank),
                )
                for index in all_indexes
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    return [corpus[index]["document_id"] for index, _ in ranked]


def run_benchmark(model_name: str, top_k: int = 5) -> dict[str, Any]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, local_files_only=True)
    report: dict[str, Any] = {
        "dataset_version": dataset["version"],
        "synthetic_dataset": dataset["synthetic"],
        "model": model_name,
        "top_k": top_k,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "methods": {},
    }
    for method in ("semantic", "hybrid"):
        started = time.perf_counter()
        case_metrics = []
        for case in dataset["cases"]:
            ranked = _rank_case(method, case["query"], dataset["corpus"], model)
            metrics = retrieval_metrics(
                case["expected_evidence_ids"], ranked, top_k
            )
            case_metrics.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "retrieved_ids": ranked[:top_k],
                    **metrics,
                }
            )
        aggregate = {
            metric: mean(item[metric] for item in case_metrics)
            for metric in ("recall_at_k", "precision_at_k", "mrr", "ndcg")
        }
        report["methods"][method] = {
            "metrics": aggregate,
            "elapsed_seconds": time.perf_counter() - started,
            "cases": case_metrics,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline incident retrieval evaluation.")
    parser.add_argument("--model", default="all-mpnet-base-v2")
    parser.add_argument("--top-k", default=5, type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "evals" / "reports" / "latest.json")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be at least one")
    report = run_benchmark(args.model, args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["methods"], indent=2))
    print(f"Saved measured benchmark results to {args.output}")


if __name__ == "__main__":
    main()
