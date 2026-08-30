import json
import stat

import pytest

from browser_profiles._store import BrowserProfileStore, summarize_browser_sites


def state(value: str = "alpha") -> dict:
    return {
        "cookies": [
            {"name": "session", "value": value, "domain": ".example.test", "path": "/"},
            {"name": "support", "value": value, "domain": "auth.example.test", "path": "/"},
        ],
        "origins": [
            {
                "origin": "https://example.test",
                "localStorage": [{"name": "saved", "value": value}],
                "indexedDB": [{"name": "profile-db", "version": 1, "stores": []}],
            }
        ],
    }


def test_default_preserves_legacy_storage_state(tmp_path):
    default_dir = tmp_path / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "storage_state.json").write_text(json.dumps(state()))

    profile = BrowserProfileStore(tmp_path).ensure_default()

    assert profile.id == "default"
    assert profile.name == "Default"
    assert BrowserProfileStore(tmp_path).load_state("default")["cookies"][0]["value"] == "alpha"
    assert [site.domain for site in profile.sites] == ["auth.example.test", "example.test"]
    assert stat.S_IMODE((default_dir / "storage_state.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(default_dir.stat().st_mode) == 0o700


def test_profile_lifecycle_has_no_versions(tmp_path):
    store = BrowserProfileStore(tmp_path)
    store.ensure_default()
    profile = store.create(name="Work", icon="bi-briefcase", storage_state=state())

    assert store.get(profile.id).name == "Work"
    assert store.load_state(profile.id)["cookies"][0]["value"] == "alpha"

    renamed = store.update_metadata(profile.id, name="Client work", icon="bi-building")
    saved = store.save_state(profile.id, state("beta"))
    assert renamed.name == "Client work"
    assert saved.sites[1].indexed_db is True
    assert store.load_state(profile.id)["cookies"][0]["value"] == "beta"
    assert sorted(path.name for path in (tmp_path / profile.id).iterdir()) == [
        "profile.json",
        "storage_state.json",
    ]

    store.delete(profile.id)
    with pytest.raises(KeyError):
        store.get(profile.id)


def test_default_cannot_be_deleted(tmp_path):
    store = BrowserProfileStore(tmp_path)
    store.ensure_default()
    with pytest.raises(ValueError, match="cannot be deleted"):
        store.delete("default")


def test_site_summary_combines_cookie_and_origin_data():
    sites = summarize_browser_sites(state())
    example = next(site for site in sites if site.domain == "example.test")
    assert example.cookies == 1
    assert example.local_storage is True
    assert example.indexed_db is True


def test_metadata_update_rejects_non_text_values(tmp_path):
    store = BrowserProfileStore(tmp_path)
    store.ensure_default()

    with pytest.raises(ValueError, match="name must be text"):
        store.update_metadata("default", name=42)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid profile icon"):
        store.update_metadata("default", icon={"bad": True})  # type: ignore[arg-type]


def test_remove_domains_deletes_only_matching_cookie_and_origin_state(tmp_path):
    store = BrowserProfileStore(tmp_path)
    profile = store.create(
        name="Work",
        icon="bi-briefcase",
        storage_state={
            "cookies": [
                {"name": "root", "value": "1", "domain": ".example.test", "path": "/"},
                {"name": "auth", "value": "1", "domain": "auth.example.test", "path": "/"},
                {"name": "other", "value": "1", "domain": "other.test", "path": "/"},
            ],
            "origins": [
                {"origin": "https://example.test", "localStorage": [{"name": "a", "value": "1"}]},
                {"origin": "https://auth.example.test", "indexedDB": [{"name": "db"}]},
                {"origin": "https://other.test", "localStorage": [{"name": "b", "value": "2"}]},
            ],
        },
    )

    updated = store.remove_domains(
        profile.id,
        ["example.test", "auth.example.test"],
    )

    remaining = store.load_state(profile.id)
    assert [cookie["domain"] for cookie in remaining["cookies"]] == ["other.test"]
    assert [origin["origin"] for origin in remaining["origins"]] == ["https://other.test"]
    assert [site.domain for site in updated.sites] == ["other.test"]
    assert updated.name == "Work"


def test_clear_state_preserves_profile_identity(tmp_path):
    store = BrowserProfileStore(tmp_path)
    profile = store.create(name="Personal", icon="bi-person", storage_state=state())

    cleared = store.clear_state(profile.id)

    assert store.load_state(profile.id) == {"cookies": [], "origins": []}
    assert cleared.name == "Personal"
    assert cleared.icon == "bi-person"
    assert cleared.sites == []
