// Launches the real application and drives it. The unit suite covers the setup
// state machine with the process boundary stubbed out; this covers the boundary
// itself — the window opening, the preload bridge, and the contract between the
// state the runtime emits and the elements the setup screen expects to find.
//
// It runs against a throwaway profile directory and stops at the Welcome
// screen, so it never installs anything or touches a container runtime.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { _electron } = require('playwright-core');

const APP_DIR = path.join(__dirname, '..', '..');
const LAUNCH_TIMEOUT = 60_000;

async function launch(t) {
  const profile = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-smoke-'));
  const app = await _electron.launch({
    // The sandbox needs kernel privileges a container runner does not grant.
    args: ['.', '--no-sandbox'],
    cwd: APP_DIR,
    executablePath: require('electron'),
    env: { ...process.env, OMNIDECK_DESKTOP_USER_DATA: profile },
    timeout: LAUNCH_TIMEOUT,
  });
  t.after(async () => {
    await app.close().catch(() => {});
    await fs.promises.rm(profile, { recursive: true, force: true });
  });
  const window = await app.firstWindow();
  await window.waitForLoadState('domcontentloaded');
  return { app, window };
}

test('the application opens a visible window on a clean profile', async (t) => {
  const { app, window } = await launch(t);

  // The window is shown once its page has loaded, which is after the first
  // window exists. Sampling visibility once races that boundary, so this waits
  // for it to become visible rather than asserting it already is.
  const deadline = Date.now() + 20_000;
  let visible = false;
  while (!visible && Date.now() < deadline) {
    visible = await app.evaluate(({ BrowserWindow }) => {
      const [first] = BrowserWindow.getAllWindows();
      return Boolean(first && first.isVisible());
    });
    if (!visible) await new Promise((resolve) => setTimeout(resolve, 100));
  }

  assert.equal(visible, true, 'the window should reach the screen');
  assert.equal(await window.title(), 'omnideck');
});

test('a clean profile reaches Welcome through the real process boundary', async (t) => {
  const { window } = await launch(t);

  await window.waitForFunction(
    () => document.getElementById('title')?.textContent?.includes('Welcome'),
    null,
    { timeout: 20_000 },
  );

  assert.equal(await window.locator('#eyebrow').textContent(), 'WELCOME');
  assert.equal((await window.locator('#primary').textContent()).trim(), 'Set up omnideck');
  assert.equal(await window.locator('#primary').isVisible(), true);
  // Nothing is being installed yet, so there is no wait to fill and no failure
  // to report.
  assert.equal(await window.locator('#doctor-panel').isVisible(), false);
  assert.equal(await window.locator('#activity').isVisible(), false);
});

test('the preload exposes only the actions the setup screen uses', async (t) => {
  const { window } = await launch(t);

  const bridge = await window.evaluate(
    () => Object.keys(window.omnideckDesktop || {}).sort(),
  );

  assert.deepEqual(bridge, ['beginSetup', 'onState', 'openApp', 'retry', 'runAction']);
});

test('the setup screen has every element the renderer writes to', async (t) => {
  const { window } = await launch(t);

  // A removed element does not fail a unit test — the renderer has none — but
  // it throws on the first state that touches it, which is how an error screen
  // can break while every test still passes.
  const missing = await window.evaluate(() => [
    'eyebrow', 'title', 'detail', 'activity', 'primary', 'secondary', 'action-error',
    'spinner', 'progress-wrap', 'progress', 'footnote', 'doctor-panel', 'doctor-result',
    'diagnostic-list', 'technical-output', 'agent-dash', 'game-overlay', 'game-message',
    'game-hint', 'score', 'best',
  ].filter((id) => !document.getElementById(id)));

  assert.deepEqual(missing, [], 'the renderer writes to elements that must exist');
});

test('the theme follows the operating system preference', async (t) => {
  const { window } = await launch(t);

  const theme = await window.evaluate(() => document.documentElement.dataset.theme);

  assert.ok(['light', 'dark'].includes(theme), `expected a theme, got ${theme}`);
});
