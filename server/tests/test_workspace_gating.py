from pathlib import Path

from samida.main import _resolve_workspace


def test_non_owner_workspace_is_always_none_even_for_a_real_directory(tmp_path: Path) -> None:
    """Workspace tools (list_directory/read_file/write_file) let the model
    read and write arbitrary files on the server's own filesystem - a severe
    secret-exfiltration risk (e.g. reading the server's .env) for any
    account that isn't the operator."""
    assert _resolve_workspace(str(tmp_path), is_owner=False) is None


def test_owner_workspace_resolves_a_real_directory(tmp_path: Path) -> None:
    assert _resolve_workspace(str(tmp_path), is_owner=True) == tmp_path


def test_owner_workspace_is_none_for_a_nonexistent_path(tmp_path: Path) -> None:
    assert _resolve_workspace(str(tmp_path / "does-not-exist"), is_owner=True) is None


def test_workspace_is_none_when_no_directory_given() -> None:
    assert _resolve_workspace(None, is_owner=True) is None
    assert _resolve_workspace("   ", is_owner=True) is None
