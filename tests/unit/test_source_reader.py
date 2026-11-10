"""Tests for bounded descriptor-relative source reads."""

from __future__ import annotations

import os

import pytest

from personal_ai_brain.assets.identity import (
    FileChangedDuringReadError,
    read_file_at,
)


def test_reads_exact_file_under_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "notes.md"
    source.write_bytes(b"# Hello\n")
    snapshot = source.stat()

    result = read_file_at(
        root,
        "notes.md",
        expected_size=snapshot.st_size,
        expected_mtime_ns=snapshot.st_mtime_ns,
    )

    assert result == b"# Hello\n"
    assert source.read_bytes() == result


def test_rejects_traversal_and_absolute_paths(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    for relative in ("../outside.txt", "/etc/passwd", "folder//file.txt", "folder\\file.txt"):
        with pytest.raises(ValueError):
            read_file_at(root, relative)


def test_rejects_symlink_file_and_directory(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "linked-file.txt").symlink_to(outside / "secret.txt")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        read_file_at(root, "linked-file.txt")
    with pytest.raises(OSError):
        read_file_at(root, "linked-dir/secret.txt")


def test_rejects_source_that_exceeds_limit(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "large.bin").write_bytes(b"x" * 32)

    with pytest.raises(ValueError, match="read limit"):
        read_file_at(root, "large.bin", max_bytes=16)


def test_expected_discovery_metadata_must_match(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "notes.md"
    source.write_bytes(b"new content")

    with pytest.raises(FileChangedDuringReadError, match="size changed"):
        read_file_at(root, "notes.md", expected_size=1)


def test_requires_absolute_root(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        read_file_at(tmp_path.name, "notes.md")


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform lacks O_NOFOLLOW")
def test_rejects_symlink_root(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    (real_root / "file.txt").write_text("safe", encoding="utf-8")
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(OSError):
        read_file_at(link_root, "file.txt")
