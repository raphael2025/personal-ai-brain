from pathlib import Path

import pytest

from personal_ai_brain.assets.scanner import (
    EntryKind,
    ScanStatus,
    scan_directory,
)


def test_scan_discovers_nested_files_without_modifying_sources(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    nested = root / "docs" / "notes"
    nested.mkdir(parents=True)
    source = nested / "note.md"
    source.write_text("keep this unchanged", encoding="utf-8")
    before = source.read_bytes()

    result = scan_directory(root)

    assert result.status is ScanStatus.COMPLETE
    assert {item.relative_path for item in result.observations} == {
        "docs",
        "docs/notes",
        "docs/notes/note.md",
    }
    file_observation = next(item for item in result.observations if item.kind is EntryKind.FILE)
    assert file_observation.relative_path == "docs/notes/note.md"
    assert file_observation.size_bytes == len(before)
    assert source.read_bytes() == before


def test_missing_root_is_failed_not_an_empty_success(tmp_path: Path) -> None:
    result = scan_directory(tmp_path / "does-not-exist")

    assert result.status is ScanStatus.FAILED
    assert result.observations == ()
    assert result.issues[0].operation == "open_root"


def test_file_root_is_rejected(tmp_path: Path) -> None:
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("data", encoding="utf-8")

    result = scan_directory(file_path)

    assert result.status is ScanStatus.FAILED
    assert result.observations == ()


def test_symlink_is_recorded_but_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("not traversed", encoding="utf-8")
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    result = scan_directory(root)

    assert result.status is ScanStatus.COMPLETE
    assert len(result.observations) == 1
    assert result.observations[0].relative_path == "linked"
    assert result.observations[0].kind is EntryKind.SYMLINK


def test_empty_directory_is_a_complete_empty_scan(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()

    result = scan_directory(root)

    assert result.status is ScanStatus.COMPLETE
    assert result.observations == ()
    assert result.issues == ()
