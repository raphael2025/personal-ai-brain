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



@pytest.mark.parametrize(
    "uri,kind",
    [
        ("file:relative/archive", StorageKind.LOCAL),
        ("file://nas.local/share", StorageKind.LOCAL),
        ("smb://nas.local", StorageKind.NETWORK),
        ("nfs:///export", StorageKind.NETWORK),
    ],
)
def test_storage_root_rejects_non_absolute_or_incomplete_uri(
    uri: str, kind: StorageKind
) -> None:
    with pytest.raises(ValueError):
        StorageRoot("root-1", "Archive", uri, kind)


def test_storage_root_rejects_non_enum_kind() -> None:
    with pytest.raises(ValueError, match="StorageKind"):
        StorageRoot("root-1", "Archive", "file:///srv/archive", "local")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", 1),
        ("follow_symlinks", 0),
    ],
)
def test_storage_root_requires_boolean_flags(field: str, value: object) -> None:
    values = {
        "root_id": "root-1",
        "display_name": "Archive",
        "uri": "file:///srv/archive",
        "kind": StorageKind.LOCAL,
        "enabled": True,
        "follow_symlinks": False,
    }
    values[field] = value

    with pytest.raises(ValueError, match="boolean"):
        StorageRoot(**values)  # type: ignore[arg-type]


def test_asset_location_rejects_non_enum_availability() -> None:
    with pytest.raises(ValueError, match="LocationAvailability"):
        AssetLocation("root-1", "docs/readme.md", availability="available")  # type: ignore[arg-type]


def test_asset_location_rejects_nul_character() -> None:
    with pytest.raises(ValueError, match="NUL"):
        AssetLocation("root-1", "docs/\x00readme.md")
