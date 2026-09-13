"""PyInstaller entry point for the frozen SAMIDA backend.

`samida.main:app` has no `__main__` block of its own - it's always been
launched externally via `python -m uvicorn ...` (see desktop/main.js and
server/README.md). A frozen build has no Python/uvicorn CLI available, so
this script gives PyInstaller a single script to freeze that starts the
same app directly.
"""

import os

import uvicorn

from samida.main import app


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("SAMIDA_BACKEND_HOST", "127.0.0.1"),
        port=int(os.environ.get("SAMIDA_BACKEND_PORT", "8765")),
    )


if __name__ == "__main__":
    main()
