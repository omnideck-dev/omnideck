// Drives the failure screen through the real process boundary, and checks the
// layout at the smallest window the application allows.
//
// The failure used here is a release-file problem, which the runtime detects
// before it looks for a container runtime. That makes it the one failure that
// reproduces identically on every machine — no podman, no container, no
// network — while still exercising the whole error surface: the stage, the
// title, the phase list, and both buttons.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { APP_DIR, launchApp } = require('./harness.cjs');

const RUNTIME_DIR = path.join(APP_DIR, 'build', 'runtime');
const MANIFEST = path.join(RUNTIME_DIR, 'image-manifest.json');
const MIN_WIDTH = 880;
const MIN_HEIGHT = 620;

// A manifest that does not describe this build, put where the application looks
// for the one it shipped with. Restored afterwards, since it is part of the
// working tree rather than the profile.
async function unidentifiableRelease(t) {
  const existing = await fs.promises.readFile(MANIFEST, 'utf8').catch(() => null);
  await fs.promises.mkdir(RUNTIME_DIR, { recursive: true });
  await fs.promises.writeFile(
    MANIFEST,
    `${JSON.stringify({
      schemaVersion: 2,
      appVersion: 'not-this-build',
      imageRef: `ghcr.io/omnideck-dev/omnideck@sha256:${'b'.repeat(64)}`,
    })}\n`,
  );
  t.after(async () => {
    if (existing === null) await fs.promises.rm(MANIFEST, { force: true });
    else await fs.promises.writeFile(MANIFEST, existing);
  });
}

// A profile that has already completed setup, so startup gets past Welcome and
// reaches the checks.
function completedSetup(profile) {
  return fs.promises.writeFile(
    path.join(profile, 'setup-state.json'),
    `${JSON.stringify({
      schemaVersion: 1,
      status: 'complete',
      reason: 'first-run',
      appVersion: 'previously-installed',
      imageVersion: 'previously-installed',
      imageRef: `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`,
      imageDigest: `sha256:${'a'.repeat(64)}`,
      updatedAt: new Date().toISOString(),
    }, null, 2)}\n`,
    { mode: 0o600 },
  );
}

async function launchFailing(t) {
  await unidentifiableRelease(t);
  const { app, window } = await launchApp(t, completedSetup);
  await window.waitForFunction(
    () => document.documentElement.dataset.stage === 'error',
    null,
    { timeout: 30_000 },
  );
  return { app, window };
}

test('a release the application cannot identify reaches the failure screen', async (t) => {
  const { window } = await launchFailing(t);

  assert.equal(await window.locator('#title').textContent(), 'Download omnideck again');
  assert.equal(await window.locator('#doctor-panel').isVisible(), true);
  assert.equal(await window.locator('#doctor-result').textContent(), 'Installer issue');
});

test('the failure screen offers the action that resolves it', async (t) => {
  const { window } = await launchFailing(t);

  // Retrying cannot repair a damaged copy of the application, so the button
  // sends the person somewhere that can.
  assert.equal((await window.locator('#primary').textContent()).trim(), 'Download omnideck');
  assert.equal(
    (await window.locator('#secondary').textContent()).trim(),
    'Show diagnostic log',
  );
  assert.equal(await window.locator('#secondary').isVisible(), true);
});

test('a failure before any phase started blames no phase', async (t) => {
  const { window } = await launchFailing(t);

  const rows = await window.evaluate(() => [...document.querySelectorAll('.diagnostic-row')]
    .map((row) => ({ label: row.children[1].textContent, status: row.dataset.status })));

  assert.ok(rows.length > 0, 'the failure report should list the phases');
  assert.ok(
    rows.every((row) => row.status === 'waiting'),
    `nothing had started, so nothing should be marked: ${JSON.stringify(rows)}`,
  );
});

test('the fullest screen fits the smallest allowed window', async (t) => {
  const { app, window } = await launchFailing(t);

  // The failure screen carries the most content, and the body does not scroll:
  // anything past the bottom is unreachable rather than merely out of view.
  await app.evaluate(async ({ BrowserWindow }, size) => {
    BrowserWindow.getAllWindows()[0].setContentSize(size.width, size.height);
  }, { width: MIN_WIDTH, height: MIN_HEIGHT });
  await window.waitForTimeout(400);

  const layout = await window.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    clientHeight: document.documentElement.clientHeight,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  const primary = await window.locator('#primary').boundingBox();
  const secondary = await window.locator('#secondary').boundingBox();

  assert.ok(
    layout.scrollHeight <= layout.clientHeight + 1,
    `content overflows the window: ${layout.scrollHeight} > ${layout.clientHeight}`,
  );
  assert.ok(
    layout.scrollWidth <= layout.clientWidth + 1,
    `content overflows sideways: ${layout.scrollWidth} > ${layout.clientWidth}`,
  );
  for (const [name, box] of [['primary', primary], ['secondary', secondary]]) {
    assert.ok(box, `the ${name} button should be laid out`);
    assert.ok(
      box.y + box.height <= layout.clientHeight + 1,
      `the ${name} button is below the fold and cannot be clicked`,
    );
  }
});
