"""Run the versioned synthetic retrieval benchmark against the BM25 baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from personal_ai_brain.evaluation.bm25 import BM25Index, SearchDocument
from personal_ai_brain.evaluation.dataset import validate_dataset


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _load_corpus(dataset_dir: Path) -> list[SearchDocument]:
    corpus_dir = dataset_dir / "corpus"
    documents: list[SearchDocument] = []
    for path in sorted(corpus_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        resolved.relative_to(corpus_dir.resolve(strict=True))
        relative = path.relative_to(corpus_dir).as_posix()
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.casefold().lstrip(".") or "unknown"
        documents.append(
            SearchDocument(
                doc_id=relative,
                text=text,
                root_id=dataset_dir.name,
                document_type=suffix,
            )
        )
    if not documents:
        raise ValueError("corpus contains no readable regular files")
    return documents


def _recall_at(expected: set[str], ranked: list[str], k: int) -> float:
    return len(expected.intersection(ranked[:k])) / len(expected)


def run_benchmark(dataset_dir: Path, *, top_k: int = 10) -> dict[str, Any]:
    """Validate, index, and score the synthetic corpus; timings are observational."""
    dataset_dir = Path(dataset_dir)
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    errors = validate_dataset(dataset_dir)
    if errors:
        raise ValueError("invalid benchmark dataset: " + "; ".join(errors[:10]))

    questions_path = dataset_dir / "questions.jsonl"
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
    ]
    documents = _load_corpus(dataset_dir)
    index = BM25Index(documents)
    latency_ms: list[float] = []
    per_query: list[dict[str, Any]] = []
    recall_5: list[float] = []
    recall_10: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcg_10: list[float] = []
    citation_precision: list[float] = []

    for question in questions:
        started = time.perf_counter_ns()
        results = index.search(question["question"], limit=top_k)
        elapsed = (time.perf_counter_ns() - started) / 1_000_000
        latency_ms.append(elapsed)
        expected = set(question["expected_sources"])
        ranked = [hit.document.doc_id for hit in results]

        relevant_ranks = [
            rank for rank, doc_id in enumerate(ranked, start=1) if doc_id in expected
        ]
        reciprocal_rank = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, doc_id in enumerate(ranked[:10], start=1)
            if doc_id in expected
        )
        ideal_count = min(len(expected), 10)
        ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        precision = (
            len(expected.intersection(ranked[:10])) / min(len(ranked), 10)
            if ranked else 0.0
        )

        r5 = _recall_at(expected, ranked, 5)
        r10 = _recall_at(expected, ranked, 10)
        recall_5.append(r5)
        recall_10.append(r10)
        reciprocal_ranks.append(reciprocal_rank)
        ndcg_10.append(dcg / ideal_dcg if ideal_dcg else 0.0)
        citation_precision.append(precision)
        per_query.append(
            {
                "id": question["id"],
                "category": question["category"],
                "result_ids": ranked,
                "expected_source_ids": sorted(expected),
                "recall_at_5": r5,
                "recall_at_10": r10,
                "reciprocal_rank": reciprocal_rank,
                "ndcg_at_10": ndcg_10[-1],
                "citation_precision_at_10": precision,
                "latency_ms": elapsed,
            }
        )

    dataset_digest = hashlib.sha256(
        questions_path.read_bytes()
        + b"\0"
        + b"".join(
            document.doc_id.encode("utf-8")
            + b"\0"
            + document.text.encode("utf-8")
            + b"\0"
            for document in documents
        )
    ).hexdigest()
    return {
        "benchmark": "personal-ai-brain-synthetic-v1",
        "retriever": {"name": "bm25", "k1": index.k1, "b": index.b, "top_k": top_k},
        "dataset": {
            "name": dataset_dir.name,
            "sha256": dataset_digest,
            "document_count": len(documents),
            "question_count": len(questions),
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "metrics": {
            "recall_at_5": statistics.fmean(recall_5),
            "recall_at_10": statistics.fmean(recall_10),
            "mrr": statistics.fmean(reciprocal_ranks),
            "ndcg_at_10": statistics.fmean(ndcg_10),
            "citation_precision_at_10": statistics.fmean(citation_precision),
            "latency_p50_ms": _percentile(latency_ms, 0.50),
            "latency_p95_ms": _percentile(latency_ms, 0.95),
        },
        "queries": per_query,
        "limitations": [
            "Synthetic corpus only; not representative of personal archives.",
            "Source paths are evidence IDs; persistent chunk/version provenance is not integrated.",
            "Latency is a small in-process measurement and is not a production capacity benchmark.",
            "The benchmark evaluates source retrieval, not answer correctness or semantic "
            "relevance beyond labelled source IDs.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PAB synthetic BM25 benchmark")
    parser.add_argument(
        "dataset",
        nargs="?",
        default="evaluation/datasets/synthetic-v1",
        help="dataset directory (default: evaluation/datasets/synthetic-v1)",
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", type=Path, help="write machine-readable JSON to this path")
    args = parser.parse_args(argv)

    try:
        report = run_benchmark(Path(args.dataset), top_k=args.top_k)
    except (OSError, ValueError) as exc:
        print(f"benchmark error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
