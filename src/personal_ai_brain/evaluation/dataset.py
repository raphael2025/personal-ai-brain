"""Validation for the project's small, redistributable retrieval benchmark."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "id",
    "category",
    "question",
    "expected_answer",
    "expected_sources",
    "evidence",
}


def validate_dataset(dataset_dir: Path) -> list[str]:
    """Return validation errors; an empty list means the dataset is structurally valid."""
    dataset_dir = Path(dataset_dir)
    questions_path = dataset_dir / "questions.jsonl"
    corpus_dir = dataset_dir / "corpus"
    errors: list[str] = []

    if not questions_path.is_file():
        return [f"Missing questions file: {questions_path}"]
    if not corpus_dir.is_dir():
        return [f"Missing corpus directory: {corpus_dir}"]

    seen_ids: set[str] = set()
    try:
        lines = questions_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"Cannot read questions file: {type(exc).__name__}"]

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"Line {line_number}: blank lines are not allowed")
            continue
        try:
            item: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"Line {line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(item, dict):
            errors.append(f"Line {line_number}: each record must be an object")
            continue

        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            errors.append(f"Line {line_number}: missing fields {sorted(missing)}")
            continue

        question_id = item["id"]
        if not isinstance(question_id, str) or not question_id.strip():
            errors.append(f"Line {line_number}: id must be a non-empty string")
            continue
        if question_id in seen_ids:
            errors.append(f"Line {line_number}: duplicate id {question_id!r}")
        seen_ids.add(question_id)

        for field in ("category", "question", "expected_answer"):
            if not isinstance(item[field], str) or not item[field].strip():
                errors.append(f"Line {line_number}: {field} must be a non-empty string")

        sources = item["expected_sources"]
        evidence = item["evidence"]
        if not isinstance(sources, list) or not sources or not all(
            isinstance(source, str) and source for source in sources
        ):
            errors.append(f"Line {line_number}: expected_sources must be a non-empty string list")
            continue
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(span, str) and span for span in evidence
        ):
            errors.append(f"Line {line_number}: evidence must be a non-empty string list")
            continue

        source_text: list[str] = []
        for source in sources:
            relative = Path(source)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"Line {line_number}: unsafe source path {source!r}")
                continue
            source_path = corpus_dir / relative
            try:
                resolved = source_path.resolve(strict=True)
                resolved.relative_to(corpus_dir.resolve(strict=True))
            except (OSError, ValueError):
                errors.append(f"Line {line_number}: source does not exist inside corpus: {source!r}")
                continue
            if not resolved.is_file():
                errors.append(f"Line {line_number}: source is not a file: {source!r}")
                continue
            source_text.append(resolved.read_text(encoding="utf-8", errors="replace"))

        joined_text = "\n".join(source_text)
        for span in evidence:
            if span not in joined_text:
                errors.append(f"Line {line_number}: evidence span not found in expected sources: {span!r}")

    if not seen_ids:
        errors.append("Dataset contains no questions")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m personal_ai_brain.evaluation.dataset DATASET_DIR")
        return 2
    errors = validate_dataset(Path(sys.argv[1]))
    if errors:
        print("\n".join(errors))
        return 1
    print("Dataset is structurally valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
