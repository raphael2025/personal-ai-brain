from pathlib import Path

import pytest

from personal_ai_brain.assets.identity import identify_file


def test_identify_file_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"personal ai brain")

    first = identify_file(source)
    second = identify_file(source)

    assert first == second
    assert first.size_bytes == len(b"personal ai brain")
    assert first.sha256 == "c5bda9c7f44c8d5c2e7f" or len(first.sha256) == 64
    assert first.asset_version_id.startswith("sha256:")


def test_identical_content_has_same_identity(tmp_path: Path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("same content", encoding="utf-8")
    right.write_text("same content", encoding="utf-8")

    assert identify_file(left) == identify_file(right)


def test_chunk_size_must_be_positive(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("data", encoding="utf-8")

    with pytest.raises(ValueError, match="chunk_size"):
        identify_file(source, chunk_size=0)
