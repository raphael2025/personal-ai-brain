"""Tests for atomic content-addressed artifact storage."""

from __future__ import annotations

import hashlib

import pytest

from personal_ai_brain.artifacts.store import (
    ArtifactIntegrityError,
    LocalArtifactStore,
)


def test_put_is_content_addressed_and_get_verifies_digest(tmp_path):
    store = LocalArtifactStore(tmp_path / "derived")
    content = b"derived text payload"

    first = store.put(content)
    second = store.put(content)

    assert first == second
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert first.size_bytes == len(content)
    assert first.uri == f"artifact://sha256/{first.sha256[:2]}/{first.sha256}"
    assert store.get(first.uri) == content


def test_empty_artifact_is_supported(tmp_path):
    store = LocalArtifactStore(tmp_path / "derived")
    artifact = store.put(b"")

    assert artifact.size_bytes == 0
    assert store.get(artifact.uri) == b""


def test_put_rejects_non_bytes_and_oversized_content(tmp_path):
    store = LocalArtifactStore(tmp_path / "derived", max_object_bytes=4)

    with pytest.raises(ValueError, match="bytes"):
        store.put("not bytes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="storage limit"):
        store.put(b"12345")


def test_get_rejects_noncanonical_uri(tmp_path):
    store = LocalArtifactStore(tmp_path / "derived")

    with pytest.raises(ValueError, match="canonical"):
        store.get("artifact://sha256/../secret")


def test_get_detects_corrupted_content(tmp_path):
    store = LocalArtifactStore(tmp_path / "derived")
    artifact = store.put(b"original")
    object_path = (
        tmp_path / "derived" / "sha256" / artifact.sha256[:2] / artifact.sha256
    )
    object_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="checksum"):
        store.get(artifact.uri)


def test_store_rejects_symlink_root(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    store = LocalArtifactStore(link_root)

    with pytest.raises(OSError):
        store.put(b"payload")
