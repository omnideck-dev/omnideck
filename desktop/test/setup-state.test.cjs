const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  SETUP_STATE_FILENAME,
  SETUP_STATE_SCHEMA,
  isSetupState,
  readSetupState,
  writeSetupState,
} = require('../src/setup-state.cjs');

test('setup state records the exact image digest used by a completed setup', async (context) => {
  const userDataPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-state-test-'));
  context.after(() => fs.rm(userDataPath, { recursive: true, force: true }));
  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`;

  const written = await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'update',
    appVersion: '0.1.0-alpha.4',
    imageVersion: '0.1.0-alpha.4',
    imageRef,
  });

  assert.equal(written.imageDigest, `sha256:${'a'.repeat(64)}`);
  assert.deepEqual(await readSetupState(userDataPath), written);
});

test('an installation recorded before the version was tracked is still an installation', async (context) => {
  // The earlier shape did not record which release was installed. Rejecting it
  // outright would make an existing installation look like a computer omnideck
  // had never been set up on, so it is read as what it plainly is: the release
  // the application that wrote it shipped with.
  const userDataPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-state-test-'));
  context.after(() => fs.rm(userDataPath, { recursive: true, force: true }));
  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'e'.repeat(64)}`;
  await fs.writeFile(
    path.join(userDataPath, SETUP_STATE_FILENAME),
    `${JSON.stringify({
      schemaVersion: 1,
      status: 'complete',
      reason: 'first-run',
      appVersion: '0.1.0-alpha.5',
      imageRef,
      imageDigest: `sha256:${'e'.repeat(64)}`,
      updatedAt: new Date().toISOString(),
    })}\n`,
  );

  const state = await readSetupState(userDataPath);

  assert.equal(state.schemaVersion, SETUP_STATE_SCHEMA);
  assert.equal(state.imageVersion, '0.1.0-alpha.5');
  assert.equal(state.imageRef, imageRef);
  assert.equal(state.status, 'complete');
});

test('invalid or partial setup state is ignored safely', async (context) => {
  const userDataPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-state-test-'));
  context.after(() => fs.rm(userDataPath, { recursive: true, force: true }));
  await fs.writeFile(
    path.join(userDataPath, SETUP_STATE_FILENAME),
    '{"status":"complete"}\n',
  );

  assert.equal(await readSetupState(userDataPath), null);
  assert.equal(isSetupState({ status: 'complete' }), false);
});
