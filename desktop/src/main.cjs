const fsp = require('node:fs/promises');
const path = require('node:path');
const {
  app,
  BrowserWindow,
  ipcMain,
  nativeTheme,
  Notification,
  session,
  shell,
} = require('electron');
const { pathToFileURL } = require('node:url');

const { OmnideckRuntime } = require('./runtime.cjs');
const { findUpdate, selectUpdate } = require('./updates.cjs');
const { readUpdateState, writeUpdateState } = require('./update-state.cjs');
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
const REPOSITORY = 'omnideck-dev/omnideck';
// Long enough that the first check never competes with opening, and rare enough
// that a machine left running for a week makes a handful of requests.
const UPDATE_FIRST_CHECK_MS = 2 * 60 * 1000;
const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000;

let mainWindow;
let runtime;
let setupRunning = false;
let zoomFactor = 1;
let availableUpdate = null;
// The version already answered with Later, so the notice does not ask again
// about one that is already settled.
let deferredVersion = null;
let updateTimer;

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

function assertAppSender(event) {
  if (!isAppUrl(event.senderFrame?.url)) {
    throw new Error('This action is only available inside omnideck.');
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

async function openOmnideck() {
  await mainWindow.loadURL(runtime.appUrl);
  scheduleUpdateChecks();
}

// Runs setup and lets the caller decide what a failure means. Every entry point
// but one wants it reported on screen; the one that does not is an update
// nobody asked for. Returns whether setup actually ran to completion, so a
// caller that clears state on success cannot mistake a declined run for one.
async function runSetup(reason) {
  if (setupRunning) return false;
  setupRunning = true;
  try {
    await runtime.setup(reason);
    return true;
  } finally {
    setupRunning = false;
  }
}

async function beginSetup(reason = runtime.setupReason) {
  try {
    await runSetup(reason);
  } catch (error) {
    runtime.reportFailure(error);
  }
}

// Whether the window is somewhere a person would see what it is showing.
// Minimised counts as out of sight; so does a window that never opened.
function windowIsInSight() {
  if (!mainWindow || mainWindow.isDestroyed()) return false;
  if (!mainWindow.isVisible() || mainWindow.isMinimized()) return false;
  return isAppUrl(mainWindow.webContents.getURL());
}

function updatePayload() {
  if (!availableUpdate) return null;
  return {
    version: availableUpdate.version,
    deferred: deferredVersion === availableUpdate.version,
  };
}

function publishUpdate() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  // Only the application itself shows this. The setup screen has its own
  // reporting and is already saying something more urgent.
  if (!isAppUrl(mainWindow.webContents.getURL())) return;
  mainWindow.webContents.send('omnideck:update', updatePayload());
}

// The application holds these preferences; this copies them to where they can
// be read at the one moment the application is not running. It follows that
// changing one takes effect from the next launch.
async function rememberPreferences() {
  try {
    const response = await fetch(`${runtime.appUrl}/api/settings`);
    if (!response.ok) return;
    const settings = await response.json();
    await writeUpdateState(app.getPath('userData'), {
      automatic: settings.software_updates_automatic !== false,
      notify: settings.software_updates_notify !== false,
    });
  } catch {
    // They simply stay as last known.
  }
}

async function checkForUpdate() {
  const installedVersion = await runtime.installedVersion();
  if (!installedVersion) return;
  const userData = app.getPath('userData');
  const previous = await readUpdateState(userData);

  let found = null;
  try {
    found = await findUpdate({
      repository: REPOSITORY,
      installedVersion,
      skippedVersion: previous.skippedVersion,
    });
  } catch (error) {
    // No network, or a registry having a bad day. Neither is worth telling
    // anyone about, and the next check is a few hours away.
    await runtime.appendLog(`update check failed: ${error.message}`);
    return;
  }

  availableUpdate = found;
  deferredVersion = previous.deferredVersion;
  await writeUpdateState(userData, {
    checkedAt: new Date().toISOString(),
    version: found?.version || null,
    imageRef: found?.imageRef || null,
  });
  // Announced once per release, and only when the notice inside omnideck
  // cannot be seen — a window someone is looking at says this already, and
  // saying it twice over their work is exactly what this is meant not to do.
  // Someone who asked not to be told is not told anywhere; the settings page
  // still shows it.
  const worthAnnouncing = found
    && found.version !== previous.version
    && previous.notify
    && !windowIsInSight();
  if (worthAnnouncing && Notification.isSupported()) {
    new Notification({
      title: 'An omnideck update is ready',
      body: `Version ${found.version} can be installed from omnideck.`,
      silent: true,
    }).show();
  }
  publishUpdate();
}

function scheduleUpdateChecks() {
  if (updateTimer) return;
  const check = () => {
    void rememberPreferences().then(checkForUpdate).catch(() => {});
  };
  updateTimer = setTimeout(() => {
    check();
    updateTimer = setInterval(check, UPDATE_INTERVAL_MS);
    updateTimer.unref?.();
  }, UPDATE_FIRST_CHECK_MS);
  updateTimer.unref?.();
}

// An update to apply before the window opens, or null. Reads only local state,
// so launching never waits on the network: what it acts on is what the last
// session found.
async function updateToApplyAtLaunch() {
  const stored = await readUpdateState(app.getPath('userData'));
  if (!stored.version || !stored.imageRef) return null;
  // Either updates are applied on their own, or this one was put off until
  // now — which is the same request for one version, without turning anything
  // on for the ones after it.
  const asked = stored.automatic || stored.deferredVersion === stored.version;
  if (!asked) return null;
  // Judged by the same rule the registry answer is judged by, so a release
  // installed by other means, or since skipped, cannot be applied here either.
  const chosen = selectUpdate({
    tags: [stored.version],
    installedVersion: await runtime.installedVersion(),
    skippedVersion: stored.skippedVersion,
  });
  return chosen ? { version: chosen, imageRef: stored.imageRef } : null;
}

async function bootstrap() {
  try {
    const pending = await updateToApplyAtLaunch();
    if (pending) {
      runtime.updateTarget = pending;
      try {
        await runSetup('update');
        runtime.updateTarget = null;
        await writeUpdateState(app.getPath('userData'), {
          deferredVersion: null, version: null, imageRef: null,
        });
        availableUpdate = null;
        deferredVersion = null;
        return;
      } catch (error) {
        // An update nobody was waiting for must never become the reason
        // omnideck will not open. What is installed still works, so this falls
        // through to opening it.
        runtime.updateTarget = null;
        await runtime.appendLog(`update at launch failed: ${error.message}`);
      }
    }

    const result = await runtime.startExisting();
    if (result.action === 'open') {
      await openOmnideck();
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

    runtime = new OmnideckRuntime({
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
      return openOmnideck();
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

    ipcMain.handle('omnideck:update-current', (event) => {
      assertAppSender(event);
      return updatePayload();
    });

    // Looking now rather than waiting for the next scheduled look. This is what
    // the settings page offers once someone has asked not to be told.
    ipcMain.handle('omnideck:update-check', async (event) => {
      assertAppSender(event);
      await rememberPreferences();
      await checkForUpdate();
      return updatePayload();
    });

    // The application asks for the update it was told about, and answers for
    // it. Installing takes over the window, because replacing what is running
    // means what is running has to stop.
    ipcMain.handle('omnideck:update-action', async (event, action) => {
      assertAppSender(event);
      if (!availableUpdate) throw new Error('There is no update to act on.');
      if (action === 'skip') {
        await writeUpdateState(app.getPath('userData'), {
          skippedVersion: availableUpdate.version,
          deferredVersion: null,
          version: null,
          imageRef: null,
        });
        availableUpdate = null;
        publishUpdate();
        return;
      }
      // Later means the same thing whether or not updates are applied on their
      // own: install it the next time omnideck is opened, when nothing is
      // running to interrupt.
      if (action === 'later') {
        await writeUpdateState(app.getPath('userData'), {
          deferredVersion: availableUpdate.version,
        });
        deferredVersion = availableUpdate.version;
        publishUpdate();
        return;
      }
      if (action !== 'install') throw new Error('Unknown action.');
      runtime.updateTarget = availableUpdate;
      await mainWindow.loadFile(SETUP_PAGE);
      try {
        if (!await runSetup('update')) return;
      } catch (error) {
        // The update someone asked for is still the one they asked for. Nothing
        // is forgotten: the target stays chosen so trying again from the setup
        // screen applies it, and what was found stays recorded so the next
        // launch can. Clearing either one here would quietly substitute the
        // release this copy shipped with for the one that was requested.
        runtime.reportFailure(error);
        return;
      }
      runtime.updateTarget = null;
      await writeUpdateState(app.getPath('userData'), {
        deferredVersion: null, version: null, imageRef: null,
      });
      availableUpdate = null;
      deferredVersion = null;
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
