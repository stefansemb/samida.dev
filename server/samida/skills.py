from pathlib import Path

_RESERVED_NAMES = {"readme"}


class SkillError(RuntimeError):
    """Raised when a requested skill name is invalid or cannot be loaded."""


def list_skills(skills_root: Path) -> list[str]:
    """Return the names (filename stem) of available skill files."""
    if not skills_root.is_dir():
        return []
    return sorted(
        path.stem
        for path in skills_root.glob("*.md")
        if path.stem.lower() not in _RESERVED_NAMES
    )


def load_skill(skills_root: Path, name: str) -> str:
    """Load a skill's raw markdown content by name (filename stem, no extension)."""
    if not name or name.lower() in _RESERVED_NAMES or "/" in name or "\\" in name or ".." in name:
        raise SkillError(f"Unknown skill: {name}")
    root = skills_root.resolve()
    candidate = (root / f"{name}.md").resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise SkillError(f"Unknown skill: {name}")
    content = candidate.read_text(encoding="utf-8").strip()
    if not content:
        raise SkillError(f"Skill file is empty: {name}")
    return content
