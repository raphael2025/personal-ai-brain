# Development Setup

This guide is for contributors working on the source code. It is not an end-user installation guide; the project is not production-ready.

## Requirements

- Python 3.11 or newer
- Git
- A supported operating system (Linux, macOS, or Windows)

## Clone and create an isolated environment

```bash
git clone https://github.com/raphael2025/personal-ai-brain.git
cd personal-ai-brain

python -m venv .venv
```

Activate the environment:

```bash
# Linux / macOS / WSL
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

Install the package and development tools:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run quality checks

```bash
ruff check .
pytest
```

The CI workflow runs these checks on Python 3.11, 3.12, and 3.13.

## Current implemented functionality

- `personal_ai_brain.assets.identity.identify_file`: streaming SHA-256 content identity for a regular file.
- `personal_ai_brain.assets.scanner.scan_directory`: read-only directory discovery, with symlinks recorded but not traversed and incomplete scans distinguished from complete scans.

Example:

```python
from pathlib import Path

from personal_ai_brain.assets.scanner import scan_directory

result = scan_directory(Path("/path/to/archive"))
print(result.status)
for observation in result.observations:
    print(observation.relative_path, observation.kind, observation.size_bytes)
```

Do not use PARTIAL or FAILED scan results to infer that previously known files were deleted. Only a COMPLETE scan is eligible for later reconciliation logic.

## Contribution rules

- Never test against a real personal archive in CI.
- Use temporary directories and synthetic fixtures.
- Do not write to, rename, move, or delete source files in discovery code.
- Do not follow symlinks unless a separately reviewed feature explicitly requires it.
- Add tests for errors and interrupted scans, not only happy paths.
- Keep performance claims tied to reproducible benchmark runs.
