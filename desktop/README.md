# SAMIDA Desktop

Runs SAMIDA fully locally as a real desktop app: no login, no shared
server, no browser sandbox for file access. A single local account is
auto-provisioned on first launch (no login screen).

## Status

Two ways to run this, chosen automatically by `app.isPackaged`:

- **Dev mode** (`npm start`): spawns the project's own `.venv` and the
  `web/` dev server as child processes. The machine needs the same
  `.venv` (with all Python deps installed) and `web/node_modules` that
  the rest of this repo needs.
- **Packaged** (`npm run dist`): a real, self-contained Windows
  installer - the Python backend is frozen with PyInstaller and the
  frontend is served through Electron's own embedded Node, so the
  target machine needs neither Python nor Node installed.

Windows-only for now (the bundled `.venv` path assumes
`.venv\Scripts\python.exe`).

## Run it (dev mode)

```bash
cd desktop
npm install
npm start
```

## Build a real installer

```bash
cd desktop
npm run dist
```

This runs, in order: `build-backend.ps1` (PyInstaller-freezes
`server/backend_entry.py` into `build/backend/`, and stages the
generic `instructions/`+`AGENT.md` content into `build/content/` -
**not** `memory/`, which is the owner's personal data and must never
ship in the installer, see "Packaged mode" below), `build-web.ps1`
(runs `vinext build` with `NEXT_PUBLIC_SAMIDA_API_URL` baked to match
the packaged backend's URL, then stages a production-only
`node_modules` alongside the built `dist/` into `build/web/`), and
finally `electron-builder`, producing `release/SAMIDA Setup
<version>.exe` (NSIS installer) plus an unpacked
`release/win-unpacked/` for faster iteration.

Each script can also be run on its own (`npm run build:backend`,
`npm run build:web`) while iterating on just one side.

## How it works

- Spawns the FastAPI backend and the frontend as child processes (dev
  mode: `.venv`'s `python -m uvicorn` + `npm run dev`; packaged: the
  frozen `samida-backend.exe` + `web/prod-server.js` run through
  Electron's own embedded Node via `ELECTRON_RUN_AS_NODE`). Both are
  addressed with the exact same hostname string in either mode
  (`localhost` in dev, `127.0.0.1` when packaged) - cookies are scoped
  by hostname, not by resolved IP, so the backend and web app must
  match exactly for the session cookie to be sent to both.
- Registers (or logs into, on a later launch) one fixed local account
  and injects its session cookie into the window before loading the
  page - so there's never a login screen.
- `SAMIDA_OWNER_EMAIL` is set to that same local account, so the
  richer chat profiles and the Priorities panel work fully (there's
  only ever one user on a desktop install, so the web app's
  multi-tenant owner-gating doesn't need to restrict anything here).
- All data (`samida.db`, attachments, logs, the encryption secret key)
  lives under Electron's per-OS user data directory, not inside this
  git checkout.
- The native folder picker (`dialog.showOpenDialog`) is exposed to the
  page via `window.samidaDesktop.pickFolder()` (see `preload.js`);
  `web/app/page.tsx`'s `pickWorkspace()` uses it when present, falling
  back to the browser/tkinter flow otherwise.

### Packaged mode: instructions/AGENT.md vs. memory/

`SAMIDA_PROJECT_ROOT` (packaged) points at the bundled `content/`
directory (`instructions/` + `AGENT.md` - generic, safe to ship to
every install) while `SAMIDA_MEMORY_DIR` points at a fresh, empty,
writable folder under the per-install `userData` directory. The real
`memory/*.md` files in this repo are the owner's personal data (see
`server/samida/context.py`'s `MEMORY_ROUTES`) and are never bundled
into the installer - a missing memory file is a normal, supported
state (silently skipped, not an error), so a fresh/other install just
starts with no memories rather than failing or leaking the owner's.
