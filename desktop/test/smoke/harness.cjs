// Starting and stopping the real application, shared by the smoke files.
//
// Stopping is the part worth having in one place. Closing waits for the process
// to exit and gives up on nothing, so an instance that will not go quietly
// stops the entire suite instead of failing one test — and a stopped suite
// reports nothing at all, because output is held per file until the file ends.
// Waiting a bounded time and then killing turns that into an ordinary result.
//
// The profile directory goes with the instance that used it: on Windows a
// directory cannot be removed while the process still holds files inside it.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron } = require('playwright-core');

const APP_DIR = path.join(__dirname, '..', '..');
const LAUNCH_TIMEOUT = 60_000;
const SHUTDOWN_TIMEOUT = 15_000;

async function stop(app, profile) {
  const child = app.process();
  let timer;
  await Promise.race([
    app.close().catch(() => {}),
    new Promise((resolve) => { timer = setTimeout(resolve, SHUTDOWN_TIMEOUT); }),
  ]);
  clearTimeout(timer);
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  await fs.promises.rm(profile, {
    recursive: true,
    force: true,
    maxRetries: 10,
    retryDelay: 200,
  });
}

// Starts the application against a throwaway profile. `seed` writes whatever
// state the launch should find there; without it the profile is empty, which is
// what a computer that has never run omnideck looks like.
async function launchApp(t, seed) {
  const profile = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-smoke-'));
  await seed?.(profile);
  const app = await _electron.launch({
    // The sandbox needs kernel privileges a container runner does not grant.
    args: ['.', '--no-sandbox'],
    cwd: APP_DIR,
    executablePath: require('electron'),
    env: { ...process.env, OMNIDECK_DESKTOP_USER_DATA: profile },
    timeout: LAUNCH_TIMEOUT,
  });
  t.after(() => stop(app, profile));

  const window = await app.firstWindow();
  await window.waitForLoadState('domcontentloaded');
  return { app, window };
}

module.exports = { APP_DIR, launchApp };
