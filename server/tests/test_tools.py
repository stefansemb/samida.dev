from pathlib import Path

import pytest

from samida.tools import WorkspaceError, list_directory, read_file, resolve_in_workspace, write_file


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "notes.txt").write_text("hej", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("inre fil", encoding="utf-8")
    return tmp_path


def test_resolve_in_workspace_rejects_parent_traversal(workspace: Path) -> None:
    with pytest.raises(WorkspaceError):
        resolve_in_workspace(workspace, "../outside.txt")


def test_resolve_in_workspace_rejects_absolute_paths(workspace: Path) -> None:
    with pytest.raises(WorkspaceError):
        resolve_in_workspace(workspace, str(workspace.parent))


def test_resolve_in_workspace_allows_nested_relative_path(workspace: Path) -> None:
    resolved = resolve_in_workspace(workspace, "sub/inner.txt")
    assert resolved == (workspace / "sub" / "inner.txt").resolve()


def test_read_file_returns_content(workspace: Path) -> None:
    result = read_file(workspace, "notes.txt")
    assert result["content"] == "hej"


def test_read_file_rejects_missing_file(workspace: Path) -> None:
    with pytest.raises(WorkspaceError):
        read_file(workspace, "missing.txt")


def test_write_file_creates_parent_directories(workspace: Path) -> None:
    result = write_file(workspace, "new/dir/file.md", "# Titel")
    assert (workspace / "new" / "dir" / "file.md").read_text(encoding="utf-8") == "# Titel"
    assert result["bytes_written"] > 0


def test_write_file_rejects_escape(workspace: Path) -> None:
    with pytest.raises(WorkspaceError):
        write_file(workspace, "../escape.txt", "nej")


def test_list_directory_skips_dotfiles_and_hidden_dirs(workspace: Path) -> None:
    (workspace / ".hidden").write_text("x", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    result = list_directory(workspace, ".")
    names = {entry["name"] for entry in result["entries"]}
    assert names == {"notes.txt", "sub"}
