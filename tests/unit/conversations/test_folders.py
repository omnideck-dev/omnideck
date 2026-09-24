"""Unit tests for the conversation folder registry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from conversations._folders import (
    create_folder,
    delete_folder,
    folder_exists,
    list_folders,
    update_folder,
)


@pytest.fixture()
def _folders_file(tmp_path: Path) -> Path:
    """Point the folder registry at a temp file."""
    path = tmp_path / "conversations" / "_folders.json"
    with patch("conversations._folders._folders_path", return_value=path):
        yield path


@pytest.mark.unit
class TestFolderRegistry:
    """Create / list / update / delete folders."""

    def test_create_returns_populated_folder(self, _folders_file: Path) -> None:
        """A created folder has an id, the given name, the default icon, and a timestamp."""
        folder = create_folder("Work")
        assert folder.id
        assert folder.name == "Work"
        assert folder.icon == "bi-folder"  # default until the user picks one
        assert folder.created_at

    def test_create_with_icon(self, _folders_file: Path) -> None:
        """A supplied icon is stored on the folder."""
        folder = create_folder("Work", icon="bi-briefcase")
        assert folder.icon == "bi-briefcase"

    def test_list_returns_created_folders(self, _folders_file: Path) -> None:
        """Created folders come back from the listing."""
        create_folder("Work")
        create_folder("Side projects")
        names = [f.name for f in list_folders()]
        assert names == ["Work", "Side projects"]

    def test_order_increases_per_folder(self, _folders_file: Path) -> None:
        """Each new folder sorts after the previous one."""
        a = create_folder("A")
        b = create_folder("B")
        assert b.order > a.order

    def test_name_is_trimmed_and_capped(self, _folders_file: Path) -> None:
        """Folder names are stripped and capped at the length limit."""
        folder = create_folder("   " + "x" * 80 + "   ")
        assert folder.name == "x" * 40

    def test_update_renames(self, _folders_file: Path) -> None:
        """Updating the name persists the new name."""
        folder = create_folder("Draft")
        updated = update_folder(folder.id, name="Final")
        assert updated is not None
        assert updated.name == "Final"
        assert list_folders()[0].name == "Final"

    def test_update_reicons(self, _folders_file: Path) -> None:
        """Updating the icon persists it."""
        folder = create_folder("Work")
        update_folder(folder.id, icon="bi-star")
        assert list_folders()[0].icon == "bi-star"

    def test_update_missing_returns_none(self, _folders_file: Path) -> None:
        """Updating an unknown folder returns None."""
        assert update_folder("nope", name="x") is None

    def test_delete_removes_folder(self, _folders_file: Path) -> None:
        """Deleting a folder drops it from the registry."""
        folder = create_folder("Trash me")
        assert delete_folder(folder.id) is True
        assert list_folders() == []

    def test_delete_missing_returns_false(self, _folders_file: Path) -> None:
        """Deleting an unknown folder returns False."""
        assert delete_folder("nope") is False

    def test_folder_exists(self, _folders_file: Path) -> None:
        """folder_exists reflects registry membership."""
        folder = create_folder("Work")
        assert folder_exists(folder.id) is True
        assert folder_exists("nope") is False

    def test_empty_registry_lists_nothing(self, _folders_file: Path) -> None:
        """With no registry file, listing returns an empty list."""
        assert list_folders() == []
