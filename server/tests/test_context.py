from pathlib import Path

import pytest

import samida.context as context_module
from samida.config import Settings
from samida.context import CORE_FILES, MEMORY_FILE_ABSTRACTS, ContextBuilder, ContextError
from samida.schemas import ChatMessage


PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Deliberately shares no tokens with any MEMORY_ROUTES keyword set, so keyword
# routing selects nothing and the semantic fallback path is what's exercised.
_NO_KEYWORD_OVERLAP_QUERY = "How fast is your internet connection right now?"


async def test_core_instructions_are_always_loaded() -> None:
    context = await ContextBuilder(PROJECT_ROOT).build(
        [ChatMessage(role="user", content="Hej!")],
        profile="samida-standard",
        is_owner=True,
    )

    assert context.included_files[:5] == ["AGENT.md", "instructions/safety.md", "instructions/work-rules.md", "instructions/communication-style.md", "instructions/memory-policy.md"]
    assert "You are SAMIDA" in context.system_message.content


async def test_project_and_technical_memory_are_selected_for_unreal_request() -> None:
    context = await ContextBuilder(PROJECT_ROOT).build(
        [
            ChatMessage(
                role="user",
                content="Hjälp mig med mitt Pirate Survival-projekt i Unreal.",
            )
        ],
        profile="samida-standard",
        is_owner=True,
    )

    assert "memory/projects.md" in context.included_files
    assert "memory/technical-context.md" in context.included_files
    assert "memory/personal.md" not in context.included_files


async def test_non_owner_is_downgraded_to_minimal_regardless_of_requested_profile() -> None:
    """The richer profiles load memory/*.md - the operator's personal facts,
    projects, and technical setup - which aren't scoped per user, so only the
    owner account may use anything but "minimal"."""
    context = await ContextBuilder(PROJECT_ROOT).build(
        [ChatMessage(role="user", content="Hjälp mig med mitt Pirate Survival-projekt i Unreal.")],
        profile="samida-standard",
        is_owner=False,
    )

    assert context.included_files == list(CORE_FILES)


async def test_personal_memory_is_not_loaded_for_unrelated_request() -> None:
    context = await ContextBuilder(PROJECT_ROOT).build(
        [ChatMessage(role="user", content="Förklara vad en REST-endpoint är.")]
    )

    assert "memory/personal.md" not in context.included_files


async def test_semantic_fallback_selects_best_matching_file(monkeypatch) -> None:
    target_abstract = MEMORY_FILE_ABSTRACTS["memory/technical-context.md"]

    async def fake_embed_text(text: str, settings: Settings) -> list[float]:
        return [1.0, 0.0] if text in (_NO_KEYWORD_OVERLAP_QUERY, target_abstract) else [0.0, 1.0]

    monkeypatch.setattr(context_module, "embed_text", fake_embed_text)

    builder = ContextBuilder(PROJECT_ROOT, settings=Settings(memory_semantic_fallback_enabled=True))
    context = await builder.build(
        [ChatMessage(role="user", content=_NO_KEYWORD_OVERLAP_QUERY)],
        profile="samida-standard",
        is_owner=True,
    )

    assert "memory/technical-context.md" in context.included_files


async def test_semantic_fallback_failure_degrades_to_keyword_only(monkeypatch) -> None:
    async def failing_embed_text(text: str, settings: Settings) -> None:
        return None

    monkeypatch.setattr(context_module, "embed_text", failing_embed_text)

    builder = ContextBuilder(PROJECT_ROOT, settings=Settings(memory_semantic_fallback_enabled=True))
    context = await builder.build(
        [ChatMessage(role="user", content=_NO_KEYWORD_OVERLAP_QUERY)],
        profile="samida-standard",
        is_owner=True,
    )

    assert not any(path.startswith("memory/") for path in context.included_files)


async def test_active_skill_is_loaded_into_prompt_and_included_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "research-report.md").write_text("# Objective\nWrite a short report.\n", encoding="utf-8")

    context = await ContextBuilder(PROJECT_ROOT, skills_root=skills_dir).build(
        [ChatMessage(role="user", content="Skriv en rapport om X.")],
        skill="research-report",
    )

    assert "skills/research-report.md" in context.included_files
    assert "Write a short report." in context.system_message.content
    assert "ACTIVE SKILL: research-report" in context.system_message.content


async def test_unknown_skill_raises_context_error(tmp_path: Path) -> None:
    builder = ContextBuilder(PROJECT_ROOT, skills_root=tmp_path / "skills")
    with pytest.raises(ContextError):
        await builder.build([ChatMessage(role="user", content="Hej")], skill="does-not-exist")


async def test_semantic_fallback_disabled_never_calls_embeddings(monkeypatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("embed_text should not be called when the fallback is disabled")

    monkeypatch.setattr(context_module, "embed_text", boom)

    builder = ContextBuilder(PROJECT_ROOT, settings=Settings(memory_semantic_fallback_enabled=False))
    context = await builder.build(
        [ChatMessage(role="user", content=_NO_KEYWORD_OVERLAP_QUERY)],
        profile="samida-standard",
        is_owner=True,
    )

    assert not any(path.startswith("memory/") for path in context.included_files)
