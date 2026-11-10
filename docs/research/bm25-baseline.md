# BM25 Lexical Retrieval Baseline

**Status:** Initial in-memory baseline implemented; synthetic benchmark only.

## Run

From the repository root:

```bash
python -m personal_ai_brain.evaluation.dataset evaluation/datasets/synthetic-v1
python -m personal_ai_brain.evaluation.benchmark evaluation/datasets/synthetic-v1 --output benchmark-results/bm25-synthetic-v1.json
```

The benchmark has no third-party runtime dependency. It validates the dataset, indexes every regular file below `corpus/`, and evaluates the labelled source IDs in `questions.jsonl`.

## Implementation

- Unicode case-folded word tokenization.
- BM25 with `k1=1.5` and `b=0.75`.
- Deterministic tie-breaking by document ID.
- Optional root, document-type, and modified-time filters.
- Empty and no-match queries return no results.
- JSON report includes dataset digest, Python/platform details, per-query rankings, Recall@5/10, MRR, nDCG@10, citation precision@10, and P50/P95 latency.

## Interpretation limits

This is a correctness and reproducibility baseline, not evidence of production search quality or throughput. The current five-query, four-document synthetic corpus is intentionally tiny. Source paths are used as evidence identifiers; the baseline is not yet connected to persisted extracted chunks, immutable asset versions, or authorization policy. Latency values are observational and should not be compared across machines without recording environment details.

Do not add vector or graph retrieval as a production dependency until it is compared against this baseline on a larger, labelled, versioned corpus.
