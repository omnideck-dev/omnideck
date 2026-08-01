const fsp = require('node:fs/promises');
const path = require('node:path');
const {
  app,
  BrowserWindow,
  ipcMain,
  nativeTheme,
  session,
  shell,
} = require('electron');
const { pathToFileURL } = require('node:url');

const { OmniDeckRuntime } = require('./runtime.cjs');
const {
  clampZoom,
  nextZoomFactor,
  zoomActionForInput,
} = require('./zoom.cjs');
const { shouldReloadForInput } = require('./window-shortcuts.cjs');

const SETUP_PAGE = path.join(__dirname, 'setup', 'index.html');
const SETUP_URL = pathToFileURL(SETUP_PAGE).href;
// The releases index rather than /latest: GitHub excludes prereleases from
// /latest, so it has nothing to show while every release is a prerelease.
const DOWNLOAD_URL = 'https://github.com/omnideck-dev/omnideck/releases';
const SUPPORTED_SYSTEMS_URL = 'https://github.com/omnideck-dev/omnideck#prerequisites';

let mainWindow;
let runtime;
let setupRunning = false;
let zoomFactor = 1;

function zoomPreferencePath() {
  return path.join(app.getPath('userData'), 'zoom-factor');
}

async function loadZoomPreference() {
  try {
    return clampZoom(Number.parseFloat(await fsp.readFile(zoomPreferencePath(), 'utf8')));
  } catch {
    return 1;
  }
}

// Held between keystrokes so a key repeat writes once when it settles instead
// of once per event. A failure here is not worth interrupting anyone over, but
// it must be caught: an unhandled rejection takes the process down.
let zoomSaveTimer;

function saveZoomPreference() {
  clearTimeout(zoomSaveTimer);
  zoomSaveTimer = setTimeout(async () => {
    try {
      await fsp.mkdir(app.getPath('userData'), { recursive: true });
      await fsp.writeFile(zoomPreferencePath(), `${zoomFactor}\n`, { mode: 0o600 });
    } catch {
      // The zoom level is a convenience; losing it is not worth reporting.
    }
  }, 400);
}

function isAppUrl(candidate) {
  try {
    return Boolean(runtime) && new URL(candidate).origin === new URL(runtime.appUrl).origin;
  } catch {
    return false;
  }
}

function isSetupUrl(candidate) {
  try {
    return new URL(candidate).href === SETUP_URL;
  } catch {
    return false;
  }
}

function assertSetupSender(event) {
  // senderFrame is null once the sending frame has gone away, so an absent
  // frame fails the check rather than throwing a type error out of it.
  if (!isSetupUrl(event.senderFrame?.url)) {
    throw new Error('This action is only available on the omnideck setup screen.');
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 880,
    minHeight: 620,
    show: false,
    title: 'omnideck',
    // The ground colour the window paints before the page renders. Both values
    // are the canvas token from the shared design language.
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#0c0e14' : '#f8f9fb',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.removeMenu();
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.setZoomFactor(zoomFactor);
  });
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (shouldReloadForInput(input, process.platform)) {
      event.preventDefault();
      mainWindow.webContents.reloadIgnoringCache();
      return;
    }
    const action = zoomActionForInput(input, process.platform);
    if (!action) return;
    event.preventDefault();
    zoomFactor = nextZoomFactor(zoomFactor, action);
    mainWindow.webContents.setZoomFactor(zoomFactor);
    saveZoomPreference();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAppUrl(url)) {
      void mainWindow.loadURL(url);
    } else if (url.startsWith('https://') || url.startsWith('http://')) {
      void shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = isAppUrl(url) || isSetupUrl(url);
    if (!allowed) {
      event.preventDefault();
      if (url.startsWith('https://') || url.startsWith('http://')) {
        void shell.openExternal(url);
      }
    }
  });

  await mainWindow.loadFile(SETUP_PAGE);
  // Shown as soon as there is something to draw. The checks that follow can
  // take several seconds against a cold container runtime, and leaving the
  // window hidden until they finish reads as the app failing to launch.
  mainWindow.show();
}

function publishState(state) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('omnideck:state', state);
}

async function openOmniDeck() {
  await mainWindow.loadURL(runtime.appUrl);
}

async function beginSetup(reason = runtime.setupReason) {
  if (setupRunning) return;
  setupRunning = true;
  try {
    await runtime.setup(reason);
  } catch (error) {
    runtime.reportFailure(error);
  } finally {
    setupRunning = false;
  }
}

async function bootstrap() {
  try {
    const result = await runtime.startExisting();
    if (result.action === 'open') {
      await openOmniDeck();
      return;
    }
    if (result.action === 'setup') await beginSetup(result.reason);
  } catch (error) {
    runtime.reportFailure(error);
  }
}

app.setName('omnideck');
if (process.env.OMNIDECK_DESKTOP_USER_DATA) {
  app.setPath('userData', path.resolve(process.env.OMNIDECK_DESKTOP_USER_DATA));
}

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    zoomFactor = await loadZoomPreference();
    session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
      try {
        const origin = new URL(webContents.getURL()).origin;
        callback(
          origin === new URL(runtime.appUrl).origin
          && permission === 'clipboard-sanitized-write',
        );
      } catch {
        callback(false);
      }
    });

    runtime = new OmniDeckRuntime({
      userDataPath: app.getPath('userData'),
      resourcesPath: process.resourcesPath,
      allowDevelopmentImagePull: !app.isPackaged,
      onState: publishState,
    });

    ipcMain.handle('omnideck:begin-setup', (event) => {
      assertSetupSender(event);
      return beginSetup();
    });
    ipcMain.handle('omnideck:retry', (event) => {
      assertSetupSender(event);
      return beginSetup(runtime.setupReason === 'update' ? 'update' : 'repair');
    });
    ipcMain.handle('omnideck:open-app', async (event) => {
      assertSetupSender(event);
      if (runtime.currentState?.stage !== 'ready') {
        throw new Error('omnideck has not finished setup.');
      }
      return openOmniDeck();
    });
    ipcMain.handle('omnideck:action', async (event, action) => {
      assertSetupSender(event);
      // Only an action the current screen actually offers may run, so the
      // renderer cannot invoke one that belongs to a different state.
      const state = runtime.currentState;
      if (!action || (action !== state?.primaryAction && action !== state?.secondaryAction)) {
        throw new Error('That action is not available right now.');
      }
      if (action === 'supported-systems') return shell.openExternal(SUPPORTED_SYSTEMS_URL);
      if (action === 'download') return shell.openExternal(DOWNLOAD_URL);
      if (action === 'close') return app.quit();
      if (action === 'show-logs') return shell.showItemInFolder(runtime.logPath);
      throw new Error('Unknown action.');
    });

    await createWindow();
    if (process.env.OMNIDECK_DESKTOP_SMOKE_EXIT_MS) {
      const delay = Number(process.env.OMNIDECK_DESKTOP_SMOKE_EXIT_MS);
      if (Number.isFinite(delay) && delay > 0) setTimeout(() => app.quit(), delay);
    }
    await bootstrap();

    app.on('activate', async () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        await createWindow();
        await bootstrap();
      }
    });
  });
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
