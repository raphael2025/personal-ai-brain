from personal_ai_brain.assets.repository import PostgresAssetRegistryRepository


def test_path_normalizer_preserves_posix_backslash_character() -> None:
    path = r"notes\\draft.txt"
    assert PostgresAssetRegistryRepository._normalized_key(path, "v1-exact") == path
    assert (
        PostgresAssetRegistryRepository._normalized_key(path, "v1-casefold")
        == path.casefold()
    )
