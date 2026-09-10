import json
from datetime import UTC, datetime
from pathlib import Path

MAX_READ_BYTES = 200_000

TOOL_SPECS: list[dict] = [
    {
        "name": "list_directory",
        "description": (
            "Lista filer och mappar i en katalog, relativt den aktiva arbetskatalogen. "
            "Använd \".\" för att lista roten."
        ),
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relativ sökväg inom arbetskatalogen. Standard är \".\".",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Läs textinnehållet i en fil, relativt den aktiva arbetskatalogen.",
        "risk": "low",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relativ sökväg till filen inom arbetskatalogen.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Skapa eller skriv över en textfil, relativt den aktiva arbetskatalogen. "
            "Kräver användarens uttryckliga godkännande innan den faktiskt körs."
        ),
        "risk": "medium",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relativ sökväg till filen inom arbetskatalogen.",
                },
                "content": {
                    "type": "string",
                    "description": "Filens fullständiga textinnehåll.",
                },
            },
            "required": ["path", "content"],
        },
    },
]

RISK_BY_TOOL: dict[str, str] = {spec["name"]: spec["risk"] for spec in TOOL_SPECS}

_SKIP_NAMES = {"node_modules", ".venv", "__pycache__", "dist", "build", ".git"}


class WorkspaceError(RuntimeError):
    """Raised when a tool call's path escapes or misuses the approved workspace."""


def resolve_in_workspace(workspace: Path, relative_path: str) -> Path:
    workspace = workspace.resolve()
    if workspace.parent == workspace:
        raise WorkspaceError("Arbetskatalogen får inte vara en enhetsrot.")
    if not workspace.is_dir():
        raise WorkspaceError(f"Arbetskatalogen finns inte: {workspace}")

    relative_path = relative_path or "."
    if Path(relative_path).is_absolute():
        raise WorkspaceError("Sökvägen måste vara relativ till arbetskatalogen.")

    candidate = (workspace / relative_path).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise WorkspaceError(f"Sökvägen ligger utanför arbetskatalogen: {relative_path}")
    return candidate


def list_directory(workspace: Path, relative_path: str = ".") -> dict:
    target = resolve_in_workspace(workspace, relative_path)
    if not target.is_dir():
        raise WorkspaceError(f"Katalogen finns inte: {relative_path}")
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
        raise WorkspaceError(f"Filen finns inte: {relative_path}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise WorkspaceError(f"Filen är för stor för att läsas ({size} bytes, max {MAX_READ_BYTES}).")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("Filen verkar vara binär eller har okänd textkodning.") from exc
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
