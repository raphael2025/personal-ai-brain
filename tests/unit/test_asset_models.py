import pytest

from personal_ai_brain.assets.models import (
    AssetLocation,
    LocationAvailability,
    StorageKind,
    StorageRoot,
)


def test_local_storage_root_accepts_file_uri() -> None:
    root = StorageRoot("root-1", "Laptop archive", "file:///srv/archive", StorageKind.LOCAL)
    assert root.uri == "file:///srv/archive"
    assert root.follow_symlinks is False


def test_network_storage_root_requires_host_and_share() -> None:
    root = StorageRoot("nas-1", "Home NAS", "smb://nas.local/personal", StorageKind.NETWORK)
    assert root.kind is StorageKind.NETWORK


@pytest.mark.parametrize(
    "uri,kind",
    [
        ("", StorageKind.LOCAL),
        ("https://example.com/archive", StorageKind.LOCAL),
        ("smb://user:password@nas.local/share", StorageKind.NETWORK),
        ("smb://nas.local/share", StorageKind.LOCAL),
        ("file:///srv/archive", StorageKind.NETWORK),
    ],
)
def test_invalid_storage_uri_is_rejected(uri: str, kind: StorageKind) -> None:
    with pytest.raises(ValueError):
        StorageRoot("root-1", "Archive", uri, kind)


def test_asset_location_normalizes_windows_separators() -> None:
    location = AssetLocation("root-1", r"docs\notes\readme.md")
    assert location.relative_path == "docs/notes/readme.md"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../secret.txt",
        "docs/../../secret.txt",
        "C:\\Users\\secret.txt",
        "docs//file.txt",
    ],
)
def test_asset_location_rejects_absolute_or_traversal_paths(path: str) -> None:
    with pytest.raises(ValueError):
        AssetLocation("root-1", path)


def test_asset_location_keeps_availability_explicit() -> None:
    location = AssetLocation(
        "root-1",
        "docs/readme.md",
        availability=LocationAvailability.UNAVAILABLE,
    )
    assert location.availability is LocationAvailability.UNAVAILABLE
