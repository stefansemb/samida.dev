from pathlib import Path

from samida.context import CORE_FILES, ContextBuilder
from samida.schemas import ChatMessage


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_core_instructions_are_always_loaded() -> None:
    context = ContextBuilder(PROJECT_ROOT).build(
        [ChatMessage(role="user", content="Hej!")]
        ,
            profile="samida-standard",
        )

    assert context.included_files[:5] == ["AGENT.md", "instructions/safety.md", "instructions/work-rules.md", "instructions/communication-style.md", "instructions/memory-policy.md"]
    assert "You are SAMIDA" in context.system_message.content


def test_project_and_technical_memory_are_selected_for_unreal_request() -> None:
    context = ContextBuilder(PROJECT_ROOT).build(
        [
            ChatMessage(
                role="user",
                content="Hjälp mig med mitt Pirate Survival-projekt i Unreal.",
            )
        ],
        profile="samida-standard",
    )

    assert "memory/projects.md" in context.included_files
    assert "memory/technical-context.md" in context.included_files
    assert "memory/personal.md" not in context.included_files


def test_personal_memory_is_not_loaded_for_unrelated_request() -> None:
    context = ContextBuilder(PROJECT_ROOT).build(
        [ChatMessage(role="user", content="Förklara vad en REST-endpoint är.")]
    )

    assert "memory/personal.md" not in context.included_files
