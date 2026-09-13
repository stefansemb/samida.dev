// SAMIDA Desktop - runs the existing FastAPI backend and Next.js web app as
// local child processes, wraps them in a window, and transparently logs in
// a single local account so there's no login screen. Windows-first; the
// venv path assumes a Windows layout (.venv/Scripts/python.exe).
//
// This is the dev-mode shell: it spawns the project's own .venv and the
// web app's dev server directly. A real installer (PyInstaller-frozen
// backend, no Node/Python required on the target machine) is a separate,
// later packaging step.

const { app, BrowserWindow, dialog, ipcMain, session } = require('electron');
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const WEB_DIR = path.join(PROJECT_ROOT, 'web');
const VENV_PYTHON = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');

const BACKEND_PORT = 8765;
const WEB_PORT = 3200;
// Both must use the exact same literal hostname as each other - cookies are
// scoped by hostname (not by port, and "localhost" vs "127.0.0.1" count as
// different hosts even though both resolve to the loopback interface), so
// the session cookie set for one origin won't be sent to API calls against
// the other unless they match exactly. vinext/Vite's dev server always binds
// the IPv6 loopback (::1) - it ignores --host - so the backend is bound to
// ::1 too (below) and both are addressed as "localhost", which resolves to
// ::1 on this machine.
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;
const WEB_URL = `http://localhost:${WEB_PORT}`;

const LOCAL_ACCOUNT = { email: 'local@samida.desktop', password: 'samida-desktop-local-user' };

const userDataDir = app.getPath('userData');
fs.mkdirSync(userDataDir, { recursive: true });

let backendProcess = null;
let webProcess = null;

function getOrCreateSecretKey() {
  const keyPath = path.join(userDataDir, 'secret.key');
  if (fs.existsSync(keyPath)) return fs.readFileSync(keyPath, 'utf8').trim();
  // Same shape as cryptography.fernet.Fernet.generate_key(): 32 random
  // bytes, URL-safe base64 - generated here so nothing needs to shell out
  // to Python just to create it.
  const key = crypto.randomBytes(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_');
  fs.writeFileSync(keyPath, key, 'utf8');
  return key;
}

function waitForServer(url, { timeoutMs = 30_000, intervalMs = 300 } = {}) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = async () => {
      try {
        const response = await fetch(url);
        if (response.ok || response.status === 401) return resolve();
      } catch {
        // not up yet
      }
      if (Date.now() > deadline) return reject(new Error(`Timed out waiting for ${url}`));
      setTimeout(attempt, intervalMs);
    };
    void attempt();
  });
}

function startBackend() {
  const env = {
    ...process.env,
    SAMIDA_OWNER_EMAIL: LOCAL_ACCOUNT.email,
    SAMIDA_SECRET_KEY: getOrCreateSecretKey(),
    SAMIDA_DATABASE_PATH: path.join(userDataDir, 'samida.db'),
    SAMIDA_ATTACHMENTS_DIR: path.join(userDataDir, 'attachments'),
    SAMIDA_LOGS_DIR: path.join(userDataDir, 'logs'),
    SAMIDA_COOKIE_SECURE: 'false',
    SAMIDA_CORS_EXTRA_ORIGINS: WEB_URL,
    SAMIDA_PUBLIC_BASE_URL: WEB_URL,
  };
  backendProcess = spawn(
    VENV_PYTHON,
    ['-m', 'uvicorn', 'server.samida.main:app', '--host', '::1', '--port', String(BACKEND_PORT)],
    { cwd: PROJECT_ROOT, env },
  );
  backendProcess.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  backendProcess.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
}

function startWeb() {
  const env = { ...process.env, NEXT_PUBLIC_SAMIDA_API_URL: BACKEND_URL };
  // npm on Windows is a .cmd shim - spawn() can't exec it directly (EINVAL),
  // it needs a shell.
  webProcess = spawn(
    'npm',
    ['run', 'dev', '--', '--port', String(WEB_PORT)],
    { cwd: WEB_DIR, env, shell: true },
  );
  webProcess.stdout.on('data', (chunk) => process.stdout.write(`[web] ${chunk}`));
  webProcess.stderr.on('data', (chunk) => process.stderr.write(`[web] ${chunk}`));
}

async function establishLocalSession() {
  let response = await fetch(`${BACKEND_URL}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(LOCAL_ACCOUNT),
  });
  if (response.status === 409) {
    response = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(LOCAL_ACCOUNT),
    });
  }
  if (!response.ok) {
    throw new Error(`Could not establish the local SAMIDA account (status ${response.status}).`);
  }
  const setCookie = response.headers.get('set-cookie');
  const match = setCookie && /samida_session=([^;]+)/.exec(setCookie);
  if (!match) throw new Error('The backend did not return a session cookie.');
  await session.defaultSession.cookies.set({
    url: WEB_URL,
    name: 'samida_session',
    value: match[1],
    httpOnly: true,
    sameSite: 'lax',
    expirationDate: Math.floor(Date.now() / 1000) + 60 * 60 * 24 * 365,
  });
}

async function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 860,
    title: 'SAMIDA',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  await win.loadURL(WEB_URL);
}

ipcMain.handle('pick-folder', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openDirectory'] });
  return result.canceled ? null : result.filePaths[0];
});

app.whenReady().then(async () => {
  startBackend();
  startWeb();
  try {
    await Promise.all([
      waitForServer(`${BACKEND_URL}/api/health`),
      // The web dev server's first run re-bundles/optimizes dependencies
      // from scratch, which can take well over 30s.
      waitForServer(WEB_URL, { timeoutMs: 90_000 }),
    ]);
    await establishLocalSession();
    await createWindow();
  } catch (error) {
    dialog.showErrorBox('SAMIDA could not start', error instanceof Error ? error.message : String(error));
    app.quit();
  }
});

app.on('window-all-closed', () => app.quit());

function killProcessTree(child) {
  if (!child || child.pid == null) return;
  if (process.platform === 'win32') {
    // child.kill() alone leaves orphans on Windows once shell:true wraps a
    // process in cmd.exe (the web process's npm -> node chain) - only a
    // tree-kill via taskkill reliably takes the whole thing down.
    spawn('taskkill', ['/PID', String(child.pid), '/F', '/T']);
  } else {
    child.kill();
  }
}

app.on('will-quit', () => {
  killProcessTree(backendProcess);
  killProcessTree(webProcess);
});
