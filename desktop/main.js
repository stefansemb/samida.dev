// SAMIDA Desktop - runs the FastAPI backend and the web app as local child
// processes, wraps them in a window, and transparently logs in a single
// local account so there's no login screen. Windows-first.
//
// Two launch modes, chosen by `app.isPackaged`:
// - Dev (unpackaged, `npm start` in this directory): spawns the repo's own
//   Python venv (`.venv/Scripts/python.exe -m uvicorn ...`) and the web
//   app's dev server (`npm run dev`) directly - requires this repo's own
//   Python deps and node_modules to already be installed.
// - Packaged (a real installer build): spawns the PyInstaller-frozen
//   backend executable directly, and runs the built frontend's production
//   server through Electron's own embedded Node (no system Python or Node
//   install required on the target machine at all). See
//   desktop/build-backend.ps1 and desktop/build-web.ps1 for how those are
//   produced, and desktop/package.json's `build.extraResources` for how
//   they're bundled into the installer.

const { app, BrowserWindow, Menu, dialog, ipcMain, session, shell } = require('electron');
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
// the other unless they match exactly.
//
// Dev mode: vinext/Vite's dev server always binds the IPv6 loopback (::1)
// - it ignores --host - so the backend is bound to ::1 too and both are
// addressed as "localhost", which resolves to ::1 on this machine.
//
// Packaged mode: the frontend's production server (desktop/build-web.ps1
// -> web/prod-server.js) has no such constraint, but the backend's URL is
// baked into the built client bundle at build time (see
// desktop/build-web.ps1's $BackendUrl) - that value, "127.0.0.1:8765", is
// what packaged mode must actually bind/talk to, and can't be changed here
// at launch time.
const BACKEND_HOST = app.isPackaged ? '127.0.0.1' : 'localhost';
const BACKEND_BIND_HOST = app.isPackaged ? '127.0.0.1' : '::1';
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
// Must be the exact same hostname string as BACKEND_HOST above, for the
// cookie-scoping reason explained in the comment above.
const WEB_HOST = app.isPackaged ? '127.0.0.1' : 'localhost';
const WEB_URL = `http://${WEB_HOST}:${WEB_PORT}`;

const LOCAL_ACCOUNT = { email: 'local@samida.desktop', password: 'samida-desktop-local-user' };
const PROJECT_WEBSITE_URL = 'https://github.com/stefansemb/samida.dev';

const userDataDir = app.getPath('userData');
fs.mkdirSync(userDataDir, { recursive: true });
const logsDir = path.join(userDataDir, 'logs');

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

const googleOAuthConfigPath = path.join(userDataDir, 'google-oauth.json');

function readGoogleOAuthConfig() {
  // Google OAuth is a shared app-level credential, not a per-user API key
  // (see server/samida/google_integration.py), so - unlike the other
  // providers, which users add for themselves under Settings - it's
  // configured once here, by hand-editing this JSON file (see Help > Open
  // Data Folder). Absent on a fresh install; Calendar/Gmail just show as
  // "not set up" until it exists.
  try {
    const raw = JSON.parse(fs.readFileSync(googleOAuthConfigPath, 'utf8'));
    if (!raw.clientId || !raw.clientSecret) return {};
    return { SAMIDA_GOOGLE_CLIENT_ID: raw.clientId, SAMIDA_GOOGLE_CLIENT_SECRET: raw.clientSecret };
  } catch {
    return {};
  }
}

function commonBackendEnv() {
  return {
    ...process.env,
    SAMIDA_OWNER_EMAIL: LOCAL_ACCOUNT.email,
    SAMIDA_SECRET_KEY: getOrCreateSecretKey(),
    SAMIDA_DATABASE_PATH: path.join(userDataDir, 'samida.db'),
    SAMIDA_ATTACHMENTS_DIR: path.join(userDataDir, 'attachments'),
    SAMIDA_LOGS_DIR: logsDir,
    SAMIDA_COOKIE_SECURE: 'false',
    SAMIDA_CORS_EXTRA_ORIGINS: WEB_URL,
    SAMIDA_PUBLIC_BASE_URL: WEB_URL,
    // The Google OAuth callback route lives on the backend, not the
    // frontend that SAMIDA_PUBLIC_BASE_URL points at - see
    // Settings.resolved_google_oauth_base_url() for why these must differ
    // here (unlike production, nothing reverse-proxies the two together).
    SAMIDA_GOOGLE_OAUTH_BASE_URL: BACKEND_URL,
    ...readGoogleOAuthConfig(),
  };
}

function startBackend() {
  if (app.isPackaged) {
    // Frozen by desktop/build-backend.ps1 (PyInstaller --onedir), bundled
    // via extraResources at "backend/samida-backend.exe". SAMIDA_PROJECT_ROOT
    // points at the bundled generic instructions/AGENT.md content;
    // SAMIDA_MEMORY_DIR is a per-install, per-user location that starts
    // empty (never the owner's own real memory/*.md - see
    // server/samida/context.py's missing-memory-file handling, which makes
    // an empty memory dir a normal supported state rather than an error).
    const backendExe = path.join(process.resourcesPath, 'backend', 'samida-backend.exe');
    const env = {
      ...commonBackendEnv(),
      SAMIDA_PROJECT_ROOT: path.join(process.resourcesPath, 'content'),
      SAMIDA_MEMORY_DIR: path.join(userDataDir, 'memory'),
      SAMIDA_BACKEND_HOST: BACKEND_BIND_HOST,
      SAMIDA_BACKEND_PORT: String(BACKEND_PORT),
    };
    backendProcess = spawn(backendExe, [], { cwd: path.dirname(backendExe), env });
  } else {
    const env = commonBackendEnv();
    backendProcess = spawn(
      VENV_PYTHON,
      ['-m', 'uvicorn', 'server.samida.main:app', '--host', BACKEND_BIND_HOST, '--port', String(BACKEND_PORT)],
      { cwd: PROJECT_ROOT, env },
    );
  }
  backendProcess.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  backendProcess.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
}

function ensureWebNodeModulesJunction(webDir) {
  // electron-builder's extraResources copying drops any directory literally
  // named "node_modules" (see desktop/build-web.ps1), so the staged prod
  // dependencies are bundled as "node_modules_prod" instead. Node's module
  // resolution only ever looks for the literal name "node_modules", so a
  // one-time directory junction (no admin rights needed on Windows, unlike
  // a symlink) restores it before the first launch.
  const nodeModulesPath = path.join(webDir, 'node_modules');
  const stagedPath = path.join(webDir, 'node_modules_prod');
  if (!fs.existsSync(nodeModulesPath) && fs.existsSync(stagedPath)) {
    fs.symlinkSync(stagedPath, nodeModulesPath, 'junction');
  }
}

function startWeb() {
  if (app.isPackaged) {
    // Built by desktop/build-web.ps1 (vinext build, API URL baked to
    // BACKEND_URL above) and staged with a production-only node_modules,
    // bundled via extraResources at "web/". Run through Electron's own
    // embedded Node (ELECTRON_RUN_AS_NODE) so no system Node install is
    // required - see web/prod-server.js, which wraps vinext's own
    // Node-native production server (not wrangler/workerd).
    const webDir = path.join(process.resourcesPath, 'web');
    ensureWebNodeModulesJunction(webDir);
    const env = { ...process.env, ELECTRON_RUN_AS_NODE: '1', PORT: String(WEB_PORT), HOST: WEB_HOST };
    webProcess = spawn(process.execPath, [path.join(webDir, 'prod-server.js')], { cwd: webDir, env });
  } else {
    const env = { ...process.env, NEXT_PUBLIC_SAMIDA_API_URL: BACKEND_URL };
    // npm on Windows is a .cmd shim - spawn() can't exec it directly (EINVAL),
    // it needs a shell.
    webProcess = spawn(
      'npm',
      ['run', 'dev', '--', '--port', String(WEB_PORT)],
      { cwd: WEB_DIR, env, shell: true },
    );
  }
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

function openUserDataSubfolder(subfolder) {
  const target = subfolder ? path.join(userDataDir, subfolder) : userDataDir;
  fs.mkdirSync(target, { recursive: true });
  void shell.openPath(target);
}

function openGoogleOAuthConfig() {
  if (!fs.existsSync(googleOAuthConfigPath)) {
    fs.writeFileSync(googleOAuthConfigPath, JSON.stringify({ clientId: '', clientSecret: '' }, null, 2), 'utf8');
  }
  void shell.openPath(googleOAuthConfigPath);
}

function showAboutDialog() {
  dialog.showMessageBox({
    type: 'info',
    title: 'About SAMIDA',
    message: 'SAMIDA',
    detail: `Version ${app.getVersion()}\nElectron ${process.versions.electron}\n\nA local-first personal assistant.`,
    buttons: ['OK'],
  });
}

function buildApplicationMenu() {
  const template = [
    { role: 'fileMenu' },
    { role: 'editMenu' },
    { role: 'viewMenu' },
    { role: 'windowMenu' },
    {
      role: 'help',
      submenu: [
        { label: 'SAMIDA Website', click: () => void shell.openExternal(PROJECT_WEBSITE_URL) },
        { label: 'Report an Issue', click: () => void shell.openExternal(`${PROJECT_WEBSITE_URL}/issues/new`) },
        { type: 'separator' },
        { label: 'Open Data Folder', click: () => openUserDataSubfolder() },
        { label: 'Open Logs Folder', click: () => openUserDataSubfolder('logs') },
        { label: 'Set Up Google Calendar && Gmail…', click: openGoogleOAuthConfig },
        { type: 'separator' },
        { label: 'About SAMIDA', click: showAboutDialog },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(async () => {
  buildApplicationMenu();
  startBackend();
  startWeb();
  try {
    await Promise.all([
      waitForServer(`${BACKEND_URL}/api/health`),
      // The web dev server's first run re-bundles/optimizes dependencies
      // from scratch, which can take well over 30s; the packaged prod
      // server starts fast but this timeout is harmless either way.
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
    // process in cmd.exe (the dev-mode web process's npm -> node chain) -
    // only a tree-kill via taskkill reliably takes the whole thing down.
    spawn('taskkill', ['/PID', String(child.pid), '/F', '/T']);
  } else {
    child.kill();
  }
}

app.on('will-quit', () => {
  killProcessTree(backendProcess);
  killProcessTree(webProcess);
});
