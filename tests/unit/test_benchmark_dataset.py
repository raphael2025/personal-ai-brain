from pathlib import Path

import pytest

from personal_ai_brain.evaluation.dataset import validate_dataset


DATASET = (
    Path(__file__).parents[2]
    / "evaluation"
    / "datasets"
    / "synthetic-v1"
)


def test_synthetic_benchmark_dataset_is_valid() -> None:
    assert validate_dataset(DATASET) == []


def test_dataset_rejects_duplicate_ids_and_missing_evidence(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "source.md").write_text("known fact", encoding="utf-8")
    questions = (
        '{"id":"same","category":"exact","question":"Q","expected_answer":"A",'
        '"expected_sources":["source.md"],"evidence":["known fact"]}\n'
        '{"id":"same","category":"exact","question":"Q","expected_answer":"A",'
        '"expected_sources":["source.md"],"evidence":["not present"]}\n'
    )
    (tmp_path / "questions.jsonl").write_text(questions, encoding="utf-8")

    errors = validate_dataset(tmp_path)

    assert any("duplicate id" in error for error in errors)
    assert any("evidence span not found" in error for error in errors)


def test_dataset_rejects_parent_directory_source(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (tmp_path / "outside.md").write_text("secret", encoding="utf-8")
    question = (
        '{"id":"escape","category":"exact","question":"Q","expected_answer":"A",'
        '"expected_sources":["../outside.md"],"evidence":["secret"]}\n'
    )
    (tmp_path / "questions.jsonl").write_text(question, encoding="utf-8")

    errors = validate_dataset(tmp_path)

    assert any("unsafe source path" in error for error in errors)
