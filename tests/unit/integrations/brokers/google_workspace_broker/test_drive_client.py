"""Focused tests for Google Drive Shared Drive request construction."""

from __future__ import annotations

from typing import Any

import pytest

from integrations.brokers.google_workspace_broker._drive_client import DriveClient


class _Request:
    def __init__(self, result: Any = None) -> None:
        self.result = result

    def execute(self) -> Any:
        return self.result


class _Files:
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.get_media_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Request:
        self.list_calls.append(kwargs)
        return _Request({"files": [{"id": "file-1", "name": "Q3 Plan"}]})

    def get(self, **kwargs: Any) -> _Request:
        self.get_calls.append(kwargs)
        return _Request({"id": kwargs["fileId"], "name": "Q3 Plan"})

    def get_media(self, **kwargs: Any) -> _Request:
        self.get_media_calls.append(kwargs)
        return _Request()

    def create(self, **kwargs: Any) -> _Request:
        self.create_calls.append(kwargs)
        return _Request({"id": "new-file", **kwargs.get("body", {})})

    def update(self, **kwargs: Any) -> _Request:
        self.update_calls.append(kwargs)
        return _Request({"id": kwargs["fileId"]})


class _Permissions:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _Request:
        self.create_calls.append(kwargs)
        return _Request({"id": "perm-1", **kwargs["body"]})


class _Service:
    def __init__(self) -> None:
        self.file_api = _Files()
        self.permission_api = _Permissions()

    def files(self) -> _Files:
        return self.file_api

    def permissions(self) -> _Permissions:
        return self.permission_api


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[DriveClient, _Service]:
    client = DriveClient.__new__(DriveClient)
    service = _Service()
    monkeypatch.setattr(client, "_service", lambda: service)
    return client, service


def _assert_shared_drive_flags(call: dict[str, Any]) -> None:
    assert call["supportsAllDrives"] is True


def test_list_files_requests_shared_drive_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Listing a folder must surface items that live on a Shared Drive."""
    client, service = _client(monkeypatch)

    result = client.list_files("folder-1")

    call = service.file_api.list_calls[0]
    _assert_shared_drive_flags(call)
    assert call["includeItemsFromAllDrives"] is True
    assert call["corpora"] == "allDrives"
    assert result[0]["id"] == "file-1"


def test_search_files_requests_shared_drive_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search must surface items shared via a Shared Drive, not just My Drive."""
    client, service = _client(monkeypatch)

    client.search_files("name contains 'plan'")

    call = service.file_api.list_calls[0]
    _assert_shared_drive_flags(call)
    assert call["includeItemsFromAllDrives"] is True
    assert call["corpora"] == "allDrives"


class _FakeDownloader:
    """Stands in for ``MediaIoBaseDownload`` — finishes in one chunk, no I/O."""

    def __init__(self, fd: Any, request: Any) -> None:
        del fd, request

    def next_chunk(self) -> tuple[None, bool]:
        return None, True


def test_export_file_binary_download_requests_shared_drive_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downloading a non-Google-Docs file's raw bytes must work for Shared Drive files."""
    client, service = _client(monkeypatch)
    monkeypatch.setattr(
        "integrations.brokers.google_workspace_broker._drive_client.MediaIoBaseDownload",
        _FakeDownloader,
    )

    client.export_file("file-1")

    _assert_shared_drive_flags(service.file_api.get_media_calls[0])


def test_get_file_metadata_requests_shared_drive_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct metadata lookup must not fail for a Shared Drive file."""
    client, service = _client(monkeypatch)

    client.get_file_metadata("file-1")

    _assert_shared_drive_flags(service.file_api.get_calls[0])


def test_upload_and_create_folder_support_shared_drives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Writing a new file or folder into a Shared Drive folder must be allowed."""
    client, service = _client(monkeypatch)

    client.upload_file("report.txt", b"data", "text/plain", parent_id="drive-folder")
    client.create_folder("Reports", parent_id="drive-folder")

    for call in service.file_api.create_calls:
        _assert_shared_drive_flags(call)


def test_update_and_trash_support_shared_drives(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renaming, editing, or trashing a Shared Drive file must be allowed."""
    client, service = _client(monkeypatch)

    client.update_file("file-1", name="renamed.txt")
    client.trash_file("file-1")

    for call in service.file_api.update_calls:
        _assert_shared_drive_flags(call)


def test_share_file_supports_shared_drives(monkeypatch: pytest.MonkeyPatch) -> None:
    """Granting a permission on a Shared Drive file must be allowed."""
    client, service = _client(monkeypatch)

    client.share_file("file-1", "reader", "user", email="guest@example.com")

    _assert_shared_drive_flags(service.permission_api.create_calls[0])
