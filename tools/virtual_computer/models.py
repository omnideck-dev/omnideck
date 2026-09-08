"""Pydantic models and type definitions for virtual computer file system operations.

Separated from the monolithic file_system module to keep responsibilities focused.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "ApplyPatchResult",
    "DirEntry",
    "DirectoryReadResult",
    "FileReadResult",
    "InsertTextResult",
    "MakeDirsResult",
    "MoveCopyResult",
    "PathExistsResult",
    "ReadFileError",
    "ReadResult",
    "ReadTextResult",
    "RemovePathResult",
    "ReplaceInFileResult",
    "TextPatch",
    "WriteFileResult",
]


class WriteFileResult(BaseModel):
    """Result model for file write and append operations.

    Attributes:
        success: Whether the operation completed successfully.
        file_path: Path to the file that was written.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    file_path: str
    error: str | None = None


class MakeDirsResult(BaseModel):
    """Result model for directory creation operations.

    Attributes:
        success: Whether the directory creation was successful.
        dir_path: Path to the directory that was created.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    dir_path: str
    error: str | None = None


class RemovePathResult(BaseModel):
    """Result model for file and directory removal operations.

    Attributes:
        success: Whether the removal operation was successful.
        path: Path that was removed.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    path: str
    error: str | None = None


class MoveCopyResult(BaseModel):
    """Result model for file and directory move/copy operations.

    Attributes:
        success: Whether the move/copy operation was successful.
        src: Source path of the operation.
        dst: Destination path of the operation.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    src: str
    dst: str
    error: str | None = None


class PathExistsResult(BaseModel):
    """Result model for path existence checks.

    Attributes:
        exists: Whether the path exists.
        is_file: Whether the path is a file.
        is_dir: Whether the path is a directory.
        path: The path that was checked.
    """

    exists: bool
    is_file: bool
    is_dir: bool
    path: str


class ReadFileError(Exception):
    """Custom exception for errors during file reading operations."""


class DirEntry(BaseModel):
    """Represents a single directory entry.

    Attributes:
        name: Name of the file or directory.
        is_file: Whether this entry is a file.
        is_dir: Whether this entry is a directory.
    """

    name: str
    is_file: bool
    is_dir: bool


class FileReadResult(BaseModel):
    """Result model for reading file contents.

    Attributes:
        type: Always "file" to distinguish from directory reads.
        name: Name of the file that was read.
        content: File content as a string.
        encoding: Content encoding format.
    """

    type: Literal["file"] = Field(default="file", frozen=True)
    name: str
    content: str
    encoding: Literal["utf-8", "base64"]


class DirectoryReadResult(BaseModel):
    """Result model for reading directory contents.

    Attributes:
        type: Always "directory" to distinguish from file reads.
        name: Name of the directory that was read.
        entries: List of directory entries contained within.
    """

    type: Literal["directory"] = Field(default="directory", frozen=True)
    name: str
    entries: list[DirEntry]


ReadResult = FileReadResult | DirectoryReadResult


class TextPatch(BaseModel):
    """Represents a text patch operation for file editing.

    Attributes:
        old_text: Exact text to find (must match uniquely in the file).
        new_text: Replacement text.
    """

    old_text: str
    new_text: str


class ApplyPatchResult(BaseModel):
    """Result model for applying text patches to files.

    Attributes:
        success: Whether the patch was applied successfully.
        file_path: Path to the file that was patched.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    file_path: str
    error: str | None = None


# --- New results for read/search/edit ops -------------------------------------------------------


class ReadTextResult(BaseModel):
    """Result model for reading text from files with optional line range selection.

    Attributes:
        success: Whether the read operation was successful.
        file_path: Path to the file relative to the virtual computer home directory.
        content: File content or selected range as a UTF-8 string, None on failure.
        start: Inclusive start line number (1-based) if range was specified.
        end: Inclusive end line number (1-based) if range was specified.
        total_lines: Total number of lines in the file when available.
        truncated: True when content was capped at the default line limit.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    file_path: str
    content: str | None
    start: int | None = None
    end: int | None = None
    total_lines: int | None = None
    truncated: bool = False
    error: str | None = None


class ReplaceInFileResult(BaseModel):
    """Result model for text replacement operations in files.

    Attributes:
        success: Whether the replace operation was successful.
        file_path: Path to the file where replacements were made.
        replacements: Number of replacements that were performed.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    file_path: str
    replacements: int
    error: str | None = None


class InsertTextResult(BaseModel):
    """Result model for inserting text at specific locations in files.

    Attributes:
        success: Whether the text insertion was successful.
        file_path: Path to the file where text was inserted.
        occurrences: Number of insertion points where text was added.
        where: Description of where the text was inserted.
        error: Error message if the operation failed, None otherwise.
    """

    success: bool
    file_path: str
    occurrences: int
    where: str
    error: str | None = None
