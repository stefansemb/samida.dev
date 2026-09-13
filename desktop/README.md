# SAMIDA Desktop

Runs SAMIDA fully locally as a real desktop app: no login, no shared
server, no browser sandbox for file access. A single local account is
auto-provisioned on first launch (no login screen).

## Status

Dev-mode prototype - this spawns the project's own `.venv` and the
`web/` dev server as child processes. It is **not yet a standalone
installer**: the machine running it needs the same `.venv` (with all
Python deps installed) and `web/node_modules` that the rest of this
repo needs. Packaging a real installer (a frozen Python backend so end
users don't need Python at all, plus an electron-builder installer) is
a separate follow-up.

Windows-only for now (the bundled `.venv` path assumes
`.venv\Scripts\python.exe`).

## Run it

```bash
cd desktop
npm install
npm start
```

## How it works

- Spawns the FastAPI backend (`server/samida/main.py`) on `::1:8765`
  and the Next.js/vinext web app on `::1:3200` as child processes.
  Both use the same IPv6 loopback host on purpose - cookies are scoped
  by hostname, not by resolved IP, so the backend and web app must be
  addressed with the exact same hostname string ("localhost") for the
  session cookie to be sent to both.
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
