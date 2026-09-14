from pathlib import Path

import pytest

from samida.skills import SkillError, list_skills, load_skill


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    (tmp_path / "research-report.md").write_text("# Objective\nDo research.\n", encoding="utf-8")
    (tmp_path / "empty.md").write_text("   \n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Format docs, not a skill.", encoding="utf-8")
    return tmp_path


def test_list_skills_excludes_readme(skills_root: Path) -> None:
    assert list_skills(skills_root) == ["empty", "research-report"]


def test_list_skills_returns_empty_for_missing_directory(tmp_path: Path) -> None:
    assert list_skills(tmp_path / "does-not-exist") == []


def test_load_skill_returns_content(skills_root: Path) -> None:
    content = load_skill(skills_root, "research-report")
    assert "Do research." in content


def test_load_skill_rejects_unknown_name(skills_root: Path) -> None:
    with pytest.raises(SkillError):
        load_skill(skills_root, "does-not-exist")


def test_load_skill_rejects_empty_file(skills_root: Path) -> None:
    with pytest.raises(SkillError):
        load_skill(skills_root, "empty")


def test_load_skill_rejects_path_traversal(skills_root: Path) -> None:
    with pytest.raises(SkillError):
        load_skill(skills_root, "../outside")


def test_load_skill_rejects_readme_as_a_skill_name(skills_root: Path) -> None:
    with pytest.raises(SkillError):
        load_skill(skills_root, "README")
