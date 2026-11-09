from pathlib import Path

import pytest

from personal_ai_brain.assets import scanner as scanner_module
from personal_ai_brain.assets.scanner import (
    EntryKind,
    ScanStatus,
    scan_directory,
)


def test_scan_directory_discovers_nested_and_hidden_entries(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (root / ".hidden").write_text("hidden", encoding="utf-8")
    (nested / "note.txt").write_text("hello", encoding="utf-8")

    result = scan_directory(root)

    assert result.status is ScanStatus.COMPLETE
    observed = {item.relative_path: item for item in result.observations}
    assert ".hidden" in observed
    assert "nested" in observed
    assert "nested/note.txt" in observed
    assert observed["nested"].kind is EntryKind.DIRECTORY
    assert observed["nested/note.txt"].kind is EntryKind.FILE
    assert observed["nested/note.txt"].size_bytes == 5
    assert result.issues == ()


def test_scan_directory_missing_root_is_failed_not_empty_success(
    tmp_path: Path,
) -> None:
    result = scan_directory(tmp_path / "does-not-exist")

    assert result.status is ScanStatus.FAILED
    assert result.observations == ()
    assert len(result.issues) == 1
    assert result.issues[0].operation == "open_root"


def test_scan_directory_rejects_file_as_root(tmp_path: Path) -> None:
    root_file = tmp_path / "not-a-directory"
    root_file.write_text("data", encoding="utf-8")

    result = scan_directory(root_file)

    assert result.status is ScanStatus.FAILED
    assert result.observations == ()


def test_scan_directory_does_not_follow_directory_symlinks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = root / "linked-directory"

    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    result = scan_directory(root)

    assert result.status is ScanStatus.COMPLETE
    observed = {item.relative_path: item for item in result.observations}
    assert "linked-directory" in observed
    assert observed["linked-directory"].kind is EntryKind.SYMLINK
    assert "linked-directory/secret.txt" not in observed


def test_scan_directory_rejects_symlink_as_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "root-link"

    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    result = scan_directory(link)

    assert result.status is ScanStatus.FAILED
    assert result.observations == ()
    assert result.issues[0].operation == "open_root"



def test_scan_directory_does_not_follow_directory_replaced_by_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from personal_ai_brain.assets import scanner as scanner_module

    root = tmp_path / "root"
    child = root / "child"
    outside = tmp_path / "outside"
    child.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    moved = root / "child-original"

    real_open = os.open
    swapped = False

    def replace_with_symlink_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "child" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            child.rename(moved)
            child.symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(scanner_module, "_secure_traversal_supported", lambda: True)
    monkeypatch.setattr(scanner_module.os, "open", replace_with_symlink_before_open)

    result = scan_directory(root)

    assert swapped is True
    assert result.status is ScanStatus.PARTIAL
    assert "child/secret.txt" not in {item.relative_path for item in result.observations}
    assert any(
        issue.relative_path == "child" and issue.operation == "open_directory"
        for issue in result.issues
    )



def test_disappearing_file_is_reported_as_partial_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source = root / "vanish.txt"
    source.write_text("temporary", encoding="utf-8")
    real_scandir = scanner_module.os.scandir

    class RemoveBeforeStat:
        def __init__(self, iterator):
            self.iterator = iterator

        def __enter__(self):
            self.iterator.__enter__()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self.iterator.__exit__(exc_type, exc_value, traceback)

        def __iter__(self):
            return self

        def __next__(self):
            entry = next(self.iterator)
            if entry.name == "vanish.txt":
                source.unlink()
            return entry

    def disappearing_scandir(directory_fd):
        return RemoveBeforeStat(real_scandir(directory_fd))

    monkeypatch.setattr(scanner_module, "_secure_traversal_supported", lambda: True)
    monkeypatch.setattr(scanner_module.os, "scandir", disappearing_scandir)

    result = scan_directory(root)

    assert result.status is ScanStatus.PARTIAL
    assert not source.exists()
    assert len(result.issues) == 1
    assert result.issues[0].relative_path == "vanish.txt"
    assert result.issues[0].operation == "stat_entry"
    assert result.issues[0].error_type == "FileNotFoundError"
