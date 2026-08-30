"""On-disk storage for explicitly saved browser profiles.

Profiles are immutable from the Browser's point of view. They change only when
an application-level save operation calls this store with a captured Playwright
storage-state document.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from config import load_config

from browser_profiles._models import BrowserProfile, BrowserProfileSite

DEFAULT_BROWSER_PROFILE_ID = "default"
DEFAULT_BROWSER_PROFILE_NAME = "Default"
DEFAULT_BROWSER_PROFILE_ICON = "bi-globe2"
_METADATA_FILE = "profile.json"
_STATE_FILE = "storage_state.json"
_EMPTY_STATE: dict[str, list[object]] = {"cookies": [], "origins": []}
_STORE_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json_write(path: Path, value: object, *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if pretty:
                json.dump(value, handle, indent=2)
            else:
                json.dump(value, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _domain_from_origin(origin: str) -> str:
    parsed = urlparse(origin)
    return parsed.hostname or origin


def summarize_browser_sites(state: dict) -> list[BrowserProfileSite]:
    sites: dict[str, BrowserProfileSite] = {}
    for cookie in state.get("cookies", []):
        domain = str(cookie.get("domain", "")).lstrip(".")
        if not domain:
            continue
        site = sites.setdefault(domain, BrowserProfileSite(domain=domain))
        site.cookies += 1

    for origin_state in state.get("origins", []):
        domain = _domain_from_origin(str(origin_state.get("origin", "")))
        if not domain:
            continue
        site = sites.setdefault(domain, BrowserProfileSite(domain=domain))
        site.local_storage = bool(origin_state.get("localStorage"))
        site.indexed_db = bool(origin_state.get("indexedDB"))

    return sorted(sites.values(), key=lambda site: site.domain)


class BrowserProfileStore:
    """Persist browser profile metadata and Playwright storage state."""

    def __init__(self, profiles_dir: Path) -> None:
        self._profiles_dir = profiles_dir

    def _profile_dir(self, profile_id: str) -> Path:
        if not profile_id or any(part in profile_id for part in ("/", "\\", "..")):
            raise ValueError("Invalid browser profile id")
        return self._profiles_dir / profile_id

    def ensure_default(self) -> BrowserProfile:
        """Create Default metadata while preserving any legacy saved state."""
        with _STORE_LOCK:
            profile_dir = self._profile_dir(DEFAULT_BROWSER_PROFILE_ID)
            metadata_path = profile_dir / _METADATA_FILE
            state_path = profile_dir / _STATE_FILE
            profile_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(profile_dir, 0o700)
            if not state_path.exists():
                _atomic_json_write(state_path, _EMPTY_STATE, pretty=False)
            else:
                os.chmod(state_path, 0o600)
            if metadata_path.exists():
                os.chmod(metadata_path, 0o600)
                return self.get(DEFAULT_BROWSER_PROFILE_ID)

            timestamp = _now()
            profile = BrowserProfile(
                id=DEFAULT_BROWSER_PROFILE_ID,
                name=DEFAULT_BROWSER_PROFILE_NAME,
                icon=DEFAULT_BROWSER_PROFILE_ICON,
                created_at=timestamp,
                updated_at=timestamp,
                sites=summarize_browser_sites(self.load_state(DEFAULT_BROWSER_PROFILE_ID)),
            )
            self._write_metadata(profile)
            return profile

    def list(self) -> list[BrowserProfile]:
        with _STORE_LOCK:
            self.ensure_default()
            profiles: list[BrowserProfile] = []
            for path in self._profiles_dir.glob(f"*/{_METADATA_FILE}"):
                try:
                    profiles.append(BrowserProfile.model_validate_json(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            return sorted(
                profiles,
                key=lambda profile: (profile.id != DEFAULT_BROWSER_PROFILE_ID, profile.name.casefold()),
            )

    def get(self, profile_id: str) -> BrowserProfile:
        with _STORE_LOCK:
            path = self._profile_dir(profile_id) / _METADATA_FILE
            if not path.exists():
                raise KeyError(profile_id)
            return BrowserProfile.model_validate_json(path.read_text(encoding="utf-8"))

    def create(self, *, name: str, icon: str, storage_state: dict) -> BrowserProfile:
        with _STORE_LOCK:
            if not isinstance(name, str):
                raise ValueError("Profile name is required")
            if not isinstance(icon, str):
                raise ValueError("Invalid profile icon")
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Profile name is required")
            profile_id = uuid4().hex[:12]
            timestamp = _now()
            profile = BrowserProfile(
                id=profile_id,
                name=clean_name,
                icon=icon or DEFAULT_BROWSER_PROFILE_ICON,
                created_at=timestamp,
                updated_at=timestamp,
                sites=summarize_browser_sites(storage_state),
            )
            _atomic_json_write(
                self._profile_dir(profile_id) / _STATE_FILE,
                storage_state,
                pretty=False,
            )
            self._write_metadata(profile)
            return profile

    def update_metadata(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        icon: str | None = None,
    ) -> BrowserProfile:
        with _STORE_LOCK:
            profile = self.get(profile_id)
            if name is not None and not isinstance(name, str):
                raise ValueError("Profile name must be text")
            if icon is not None and not isinstance(icon, str):
                raise ValueError("Invalid profile icon")
            clean_name = name.strip() if name is not None else profile.name
            if not clean_name:
                raise ValueError("Profile name is required")
            updated = BrowserProfile.model_validate(
                {
                    **profile.model_dump(mode="json"),
                    "name": clean_name,
                    "icon": icon or profile.icon,
                    "updated_at": _now(),
                }
            )
            self._write_metadata(updated)
            return updated

    def save_state(self, profile_id: str, storage_state: dict) -> BrowserProfile:
        with _STORE_LOCK:
            profile = self.get(profile_id)
            updated = profile.model_copy(update={"updated_at": _now(), "sites": summarize_browser_sites(storage_state)})
            _atomic_json_write(
                self._profile_dir(profile_id) / _STATE_FILE,
                storage_state,
                pretty=False,
            )
            self._write_metadata(updated)
            return updated

    def remove_domains(
        self,
        profile_id: str,
        domains: Sequence[str],
    ) -> BrowserProfile:
        """Remove the saved browser data belonging to exact domain names."""
        with _STORE_LOCK:
            if not domains or any(not isinstance(domain, str) for domain in domains):
                raise ValueError("At least one domain is required")
            selected = {domain.strip().lstrip(".").casefold() for domain in domains if domain.strip().lstrip(".")}
            if not selected:
                raise ValueError("At least one domain is required")

            state = self.load_state(profile_id)
            updated_state = {
                **state,
                "cookies": [
                    cookie
                    for cookie in state.get("cookies", [])
                    if str(cookie.get("domain", "")).lstrip(".").casefold() not in selected
                ],
                "origins": [
                    origin
                    for origin in state.get("origins", [])
                    if _domain_from_origin(str(origin.get("origin", ""))).casefold() not in selected
                ],
            }
            return self.save_state(profile_id, updated_state)

    def clear_state(self, profile_id: str) -> BrowserProfile:
        """Remove all transferable browser data while preserving identity."""
        return self.save_state(profile_id, {"cookies": [], "origins": []})

    def load_state(self, profile_id: str) -> dict:
        with _STORE_LOCK:
            path = self._profile_dir(profile_id) / _STATE_FILE
            if not path.exists():
                if profile_id == DEFAULT_BROWSER_PROFILE_ID:
                    return dict(_EMPTY_STATE)
                raise KeyError(profile_id)
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid browser profile state")
            return value

    def delete(self, profile_id: str) -> None:
        with _STORE_LOCK:
            if profile_id == DEFAULT_BROWSER_PROFILE_ID:
                raise ValueError("The Default browser profile cannot be deleted")
            profile_dir = self._profile_dir(profile_id)
            if not (profile_dir / _METADATA_FILE).exists():
                raise KeyError(profile_id)
            for filename in (_METADATA_FILE, _STATE_FILE):
                path = profile_dir / filename
                if path.exists():
                    path.unlink()
            profile_dir.rmdir()

    def _write_metadata(self, profile: BrowserProfile) -> None:
        _atomic_json_write(
            self._profile_dir(profile.id) / _METADATA_FILE,
            profile.model_dump(mode="json"),
        )


def get_browser_profile_store() -> BrowserProfileStore:
    root = Path(load_config().settings.home_dir) / "browser" / "profiles"
    return BrowserProfileStore(root)


__all__ = [
    "DEFAULT_BROWSER_PROFILE_ID",
    "BrowserProfileStore",
    "get_browser_profile_store",
    "summarize_browser_sites",
]
