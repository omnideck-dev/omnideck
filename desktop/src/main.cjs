const fsp = require('node:fs/promises');
const path = require('node:path');
const {
  app,
  BrowserWindow,
  ipcMain,
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

const SETUP_PAGE = path.join(__dirname, 'setup', 'index.html');
const SETUP_URL = pathToFileURL(SETUP_PAGE).href;

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

async function saveZoomPreference() {
  await fsp.mkdir(app.getPath('userData'), { recursive: true });
  await fsp.writeFile(zoomPreferencePath(), `${zoomFactor}\n`, { mode: 0o600 });
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
  if (!isSetupUrl(event.senderFrame.url)) {
    throw new Error('This action is only available on the OmniDeck setup screen.');
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 880,
    minHeight: 620,
    show: false,
    title: 'OmniDeck',
    backgroundColor: '#0c0e14',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.removeMenu();
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents.setZoomFactor(zoomFactor);
  });
  mainWindow.webContents.on('before-input-event', (event, input) => {
    const action = zoomActionForInput(input, process.platform);
    if (!action) return;
    event.preventDefault();
    zoomFactor = nextZoomFactor(zoomFactor, action);
    mainWindow.webContents.setZoomFactor(zoomFactor);
    void saveZoomPreference();
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
}

function publishState(state) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('omnideck:state', state);
}

async function openOmniDeck() {
  await mainWindow.loadURL(runtime.appUrl);
}

async function beginSetup() {
  if (setupRunning) return;
  setupRunning = true;
  try {
    await runtime.setup();
  } catch (error) {
    runtime.reportFailure(error);
  } finally {
    setupRunning = false;
  }
}

async function bootstrap() {
  try {
    const ready = await runtime.startExisting();
    if (ready) await openOmniDeck();
  } catch (error) {
    runtime.reportFailure(error);
  }
}

app.setName('OmniDeck');
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
      return beginSetup();
    });
    ipcMain.handle('omnideck:show-logs', (event) => {
      assertSetupSender(event);
      return shell.showItemInFolder(runtime.logPath);
    });
    ipcMain.handle('omnideck:open-app', async (event) => {
      assertSetupSender(event);
      if (runtime.currentState?.stage !== 'ready') {
        throw new Error('OmniDeck has not finished setup.');
      }
      return openOmniDeck();
    });

    await createWindow();
    await bootstrap();
    if (process.env.OMNIDECK_DESKTOP_SMOKE_EXIT_MS) {
      const delay = Number(process.env.OMNIDECK_DESKTOP_SMOKE_EXIT_MS);
      if (Number.isFinite(delay) && delay > 0) setTimeout(() => app.quit(), delay);
    }

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
