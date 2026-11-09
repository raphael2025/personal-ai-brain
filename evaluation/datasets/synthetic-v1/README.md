# Synthetic Retrieval Benchmark v1

This fixture set is authored for Personal AI Brain and contains no personal or scraped data.

## Contents
- `corpus/`: tiny source corpus spanning Markdown, CSV, and Python.
- `questions.jsonl`: one JSON object per line with a gold answer, expected source IDs (relative paths), and literal evidence snippets.

## Categories
- exact lookup
- temporal lookup
- cross-file reasoning
- conflict resolution
- structured data lookup

## Validation
Run:

```bash
python -m personal_ai_brain.evaluation.dataset evaluation/datasets/synthetic-v1
```

The validator checks JSONL shape, unique question IDs, source existence, and evidence-span presence. It does not grade semantic answer quality; retrieval and answer metrics belong in the benchmark runner.

All fixtures are original project-authored synthetic examples.
