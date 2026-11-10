"""Tests for the deterministic lexical retrieval baseline."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from personal_ai_brain.evaluation.bm25 import (
    BM25Index,
    SearchDocument,
    SearchFilters,
    tokenize,
)
from personal_ai_brain.evaluation.benchmark import run_benchmark


def test_tokenizer_is_unicode_casefolded_and_ignores_punctuation():
    assert tokenize("CÉDAR, Cedar_project! 世界") == ("cédar", "cedar", "project", "世界")


def test_bm25_returns_relevant_documents_in_deterministic_order():
    index = BM25Index(
        [
            SearchDocument("b.md", "Cedar release plan for Cedar"),
            SearchDocument("a.md", "Cedar release plan for Cedar"),
            SearchDocument("c.md", "unrelated inventory"),
        ]
    )

    results = index.search("CEDAR release", limit=2)

    assert [hit.document.doc_id for hit in results] == ["a.md", "b.md"]
    assert results[0].score > 0


def test_empty_or_unmatched_queries_return_no_results():
    index = BM25Index([SearchDocument("a.md", "Cedar project")])

    assert index.search("   ") == []
    assert index.search("nonexistentterm") == []


def test_metadata_filters_are_applied_before_ranking():
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    index = BM25Index(
        [
            SearchDocument("one.md", "Cedar plan", root_id="root-a", document_type="md",
                           modified_at=timestamp),
            SearchDocument("two.txt", "Cedar plan", root_id="root-b", document_type="txt",
                           modified_at=timestamp),
        ]
    )

    results = index.search(
        "Cedar",
        filters=SearchFilters(
            root_id="root-a",
            document_type="MD",
            modified_after=datetime(2024, 1, 1, tzinfo=UTC),
            modified_before=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )

    assert [hit.document.doc_id for hit in results] == ["one.md"]


def test_invalid_index_inputs_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        BM25Index([SearchDocument("same", "one"), SearchDocument("same", "two")])
    with pytest.raises(ValueError, match="k1"):
        BM25Index([], k1=0)
    with pytest.raises(ValueError, match="limit"):
        BM25Index([]).search("query", limit=0)


def test_synthetic_benchmark_is_machine_readable_and_has_metrics():
    from pathlib import Path

    dataset = Path(__file__).parents[2] / "evaluation" / "datasets" / "synthetic-v1"
    report = run_benchmark(dataset)

    assert report["dataset"]["document_count"] == 4
    assert report["dataset"]["question_count"] == 5
    assert 0 <= report["metrics"]["recall_at_5"] <= 1
    assert 0 <= report["metrics"]["mrr"] <= 1
    assert 0 <= report["metrics"]["ndcg_at_10"] <= 1
    assert report["metrics"]["latency_p95_ms"] >= 0
    assert len(report["queries"]) == 5
    assert report["limitations"]
