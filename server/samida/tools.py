import json
from datetime import UTC, datetime
from pathlib import Path

MAX_READ_BYTES = 200_000

GENERAL_TOOL_SPECS: list[dict] = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information, news, or facts you don't already know. "
            "Works regardless of which chat model is answering."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text description using the user's configured "
            "image provider (GPT Image, Flux, or Gemini)."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Description of the image to generate.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "fetch_page",
        "description": (
            "Fetch the full text content of a specific public webpage URL. Use this after "
            "web_search to read a page in full, or when the user gives you a link directly."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full https URL of the page to read.",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get the current multi-day weather forecast for a city or place.",
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City or place name, e.g. 'Göteborg' or 'Paris, France'.",
                },
            },
            "required": ["location"],
        },
    },
    {
        "name": "list_calendar_events",
        "description": (
            "List the user's upcoming Google Calendar events. Only works if the user has "
            "connected their Google account under Settings."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of upcoming events to return. Defaults to 10.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "list_recent_emails",
        "description": (
            "List the user's recent Gmail messages (subject, sender, date, and a short snippet - "
            "not the full body). Only works if the user has connected their Google account under Settings."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional Gmail search query, e.g. 'is:unread' or 'from:boss@example.com'.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "save_note",
        "description": "Save a short personal note for the user to recall later, in any conversation.",
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The note's text content.",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall_notes",
        "description": "Recall the user's previously saved notes, optionally filtered by a keyword.",
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter notes by. Leave empty to list the most recent notes.",
                },
            },
            "required": [],
        },
    },
]

WORKSPACE_TOOL_SPECS: list[dict] = [
    {
        "name": "list_directory",
        "description": (
            "List files and folders in a directory, relative to the active working directory. "
            "Use \".\" to list the root."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the working directory. Defaults to \".\".",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Read the text content of a file, relative to the active working directory.",
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the working directory.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a text file, relative to the active working directory. "
            "Requires the user's explicit approval before it actually runs."
        ),
        "risk": "medium",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file within the working directory.",
                },
                "content": {
                    "type": "string",
                    "description": "The file's full text content.",
                },
            },
            "required": ["path", "content"],
        },
    },
]

TOOL_SPECS: list[dict] = GENERAL_TOOL_SPECS + WORKSPACE_TOOL_SPECS

RISK_BY_TOOL: dict[str, str] = {spec["name"]: spec["risk"] for spec in TOOL_SPECS}

_SKIP_NAMES = {"node_modules", ".venv", "__pycache__", "dist", "build", ".git"}


class WorkspaceError(RuntimeError):
    """Raised when a tool call's path escapes or misuses the approved workspace."""


def resolve_in_workspace(workspace: Path, relative_path: str) -> Path:
    workspace = workspace.resolve()
    if workspace.parent == workspace:
        raise WorkspaceError("The working directory cannot be a drive root.")
    if not workspace.is_dir():
        raise WorkspaceError(f"The working directory does not exist: {workspace}")

    relative_path = relative_path or "."
    if Path(relative_path).is_absolute():
        raise WorkspaceError("The path must be relative to the working directory.")

    candidate = (workspace / relative_path).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise WorkspaceError(f"The path is outside the working directory: {relative_path}")
    return candidate


def list_directory(workspace: Path, relative_path: str = ".") -> dict:
    target = resolve_in_workspace(workspace, relative_path)
    if not target.is_dir():
        raise WorkspaceError(f"The directory does not exist: {relative_path}")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if child.name.startswith(".") or child.name in _SKIP_NAMES:
            continue
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": None if child.is_dir() else child.stat().st_size,
            }
        )
    return {"path": relative_path, "entries": entries}


def read_file(workspace: Path, relative_path: str) -> dict:
    target = resolve_in_workspace(workspace, relative_path)
    if not target.is_file():
        raise WorkspaceError(f"The file does not exist: {relative_path}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise WorkspaceError(f"The file is too large to read ({size} bytes, max {MAX_READ_BYTES}).")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("The file appears to be binary or has an unknown text encoding.") from exc
    return {"path": relative_path, "content": content}


def write_file(workspace: Path, relative_path: str, content: str) -> dict:
    target = resolve_in_workspace(workspace, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": relative_path, "bytes_written": len(content.encode("utf-8"))}


def log_tool_call(
    logs_dir: Path,
    *,
    tool_name: str,
    target: str,
    risk_level: str,
    status: str,
    detail: str = "",
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now(UTC).isoformat(),
        "tool": tool_name,
        "target": target,
        "risk_level": risk_level,
        "status": status,
        "detail": detail[:500],
    }
    with (logs_dir / "tool-calls.log").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
