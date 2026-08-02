const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  SETUP_STATE_FILENAME,
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
