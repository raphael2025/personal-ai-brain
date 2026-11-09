import os
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
    assert len(first.sha256) == 64
    assert first.asset_version_id.startswith("sha256:")


def test_identical_content_has_same_identity(tmp_path: Path) -> None:
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("same content", encoding="utf-8")
    right.write_text("same content", encoding="utf-8")
    assert identify_file(left) == identify_file(right)


def test_empty_file_has_valid_identity(tmp_path: Path) -> None:
    source = tmp_path / "empty.bin"
    source.write_bytes(b"")
    identity = identify_file(source)
    assert identity.size_bytes == 0
    assert identity.sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_binary_file_is_hashed_exactly(tmp_path: Path) -> None:
    source = tmp_path / "binary.bin"
    source.write_bytes(bytes(range(256)))
    identity = identify_file(source, chunk_size=17)
    assert identity.size_bytes == 256
    assert len(identity.sha256) == 64


def test_chunk_size_must_be_positive(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="chunk_size"):
        identify_file(source, chunk_size=0)


def test_large_file_is_hashed_with_small_chunks_and_source_is_unchanged(
    tmp_path: Path,
) -> None:
    import hashlib

    payload = bytes(range(256)) * 8193
    source = tmp_path / "large.bin"
    source.write_bytes(payload)

    identity = identify_file(source, chunk_size=4093)

    assert identity.sha256 == hashlib.sha256(payload).hexdigest()
    assert identity.size_bytes == len(payload)
    assert source.read_bytes() == payload


def test_replacement_after_open_is_rejected_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from personal_ai_brain.assets import identity as identity_module
    from personal_ai_brain.assets.identity import FileChangedDuringReadError

    source = tmp_path / "changing.bin"
    original = b"original bytes"
    replacement = b"replacement bytes"
    source.write_bytes(original)
    moved = tmp_path / "opened-original.bin"
    real_open = os.open
    replaced = False

    def open_then_replace(path, flags, *args, **kwargs):
        nonlocal replaced
        descriptor = real_open(path, flags, *args, **kwargs)
        if Path(path) == source and not replaced:
            replaced = True
            source.rename(moved)
            source.write_bytes(replacement)
        return descriptor

    monkeypatch.setattr(identity_module.os, "open", open_then_replace)

    with pytest.raises(FileChangedDuringReadError):
        identify_file(source)

    assert moved.read_bytes() == original
    assert source.read_bytes() == replacement


def test_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="regular"):
        identify_file(tmp_path)


def test_symlink_to_regular_file_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("do not follow", encoding="utf-8")
    link = tmp_path / "link.txt"

    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink"):
        identify_file(link)



def test_permission_error_from_open_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from personal_ai_brain.assets import identity as identity_module

    source = tmp_path / "restricted.txt"
    source.write_text("private", encoding="utf-8")
    real_open = os.open

    def deny_source_open(path, flags, *args, **kwargs):
        if Path(path) == source:
            raise PermissionError("synthetic permission denial")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(identity_module.os, "open", deny_source_open)

    with pytest.raises(PermissionError, match="synthetic"):
        identify_file(source)


def test_in_place_mutation_during_hash_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from personal_ai_brain.assets import identity as identity_module
    from personal_ai_brain.assets.identity import FileChangedDuringReadError

    source = tmp_path / "mutating.bin"
    source.write_bytes(b"original payload")
    real_fstat = os.fstat
    calls = 0

    def mutate_before_final_stat(file_descriptor: int):
        nonlocal calls
        calls += 1
        if calls == 2:
            source.write_bytes(b"changed payload with another size")
        return real_fstat(file_descriptor)

    monkeypatch.setattr(identity_module.os, "fstat", mutate_before_final_stat)

    with pytest.raises(FileChangedDuringReadError):
        identify_file(source)

    assert calls == 2
    assert source.read_bytes() == b"changed payload with another size"



def test_identify_file_at_hashes_only_beneath_root(tmp_path: Path) -> None:
    from personal_ai_brain.assets.identity import identify_file_at

    root = tmp_path / "root"
    root.mkdir()
    nested = root / "docs"
    nested.mkdir()
    source = nested / "notes.md"
    source.write_bytes(b"descriptor relative")

    identity = identify_file_at(
        root,
        "docs/notes.md",
        expected_size=source.stat().st_size,
        expected_mtime_ns=source.stat().st_mtime_ns,
    )
    assert identity == identify_file(source)


@pytest.mark.parametrize("relative_path", ["/etc/passwd", "../secret", "docs/../secret"])
def test_identify_file_at_rejects_traversal(
    tmp_path: Path, relative_path: str
) -> None:
    from personal_ai_brain.assets.identity import identify_file_at

    with pytest.raises(ValueError, match="relative_path"):
        identify_file_at(tmp_path, relative_path)


def test_identify_file_at_rejects_symlinked_directory(tmp_path: Path) -> None:
    from personal_ai_brain.assets.identity import identify_file_at

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(OSError):
        identify_file_at(root, "linked/secret.txt")


def test_identify_file_at_rejects_stale_discovery_metadata(tmp_path: Path) -> None:
    from personal_ai_brain.assets.identity import (
        FileChangedDuringReadError,
        identify_file_at,
    )

    root = tmp_path / "root"
    root.mkdir()
    source = root / "notes.md"
    source.write_text("new content", encoding="utf-8")

    with pytest.raises(FileChangedDuringReadError, match="size changed"):
        identify_file_at(root, "notes.md", expected_size=1)



def test_identify_file_at_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    import os

    from personal_ai_brain.assets.identity import identify_file_at

    if not hasattr(os, "mkfifo"):
        pytest.skip("named pipes are unavailable on this platform")
    root = tmp_path / "root"
    root.mkdir()
    os.mkfifo(root / "pipe")

    with pytest.raises(ValueError, match="regular file"):
        identify_file_at(root, "pipe")
