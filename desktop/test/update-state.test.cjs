const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  UPDATE_STATE_FILENAME,
  readUpdateState,
  writeUpdateState,
} = require('../src/update-state.cjs');

async function profile(t) {
  const directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-update-'));
  t.after(() => fs.promises.rm(directory, { recursive: true, force: true }));
  return directory;
}

test('a computer that has never checked has nothing skipped and nothing pending', async (t) => {
  const directory = await profile(t);

  assert.deepEqual(await readUpdateState(directory), {
    schemaVersion: 1,
    skippedVersion: null,
    automatic: true,
    notify: true,
    checkedAt: null,
    version: null,
    imageRef: null,
  });
});

test('the preferences start where the application says they start', async (t) => {
  const directory = await profile(t);

  // A launch that happens before the application has ever been read has to
  // behave the same way the application would, or the first launch after
  // installing would behave unlike every launch after it.
  const state = await readUpdateState(directory);
  assert.equal(state.automatic, true);
  assert.equal(state.notify, true);
});

test('a write keeps the fields it was not given', async (t) => {
  const directory = await profile(t);
  await writeUpdateState(directory, { skippedVersion: '0.2.0', automatic: true });

  await writeUpdateState(directory, { version: '0.3.0', imageRef: 'ghcr.io/x@sha256:abc' });

  const state = await readUpdateState(directory);
  assert.equal(state.skippedVersion, '0.2.0');
  assert.equal(state.automatic, true);
  assert.equal(state.version, '0.3.0');
});

test('a skip can be lifted by skipping nothing', async (t) => {
  const directory = await profile(t);
  await writeUpdateState(directory, { skippedVersion: '0.2.0' });

  await writeUpdateState(directory, { skippedVersion: null });

  assert.equal((await readUpdateState(directory)).skippedVersion, null);
});

test('a damaged file reads as a computer that has never checked', async (t) => {
  const directory = await profile(t);
  await fs.promises.writeFile(path.join(directory, UPDATE_STATE_FILENAME), '{ not json');

  const state = await readUpdateState(directory);

  // Losing this file costs a re-check and a forgotten skip. Refusing to start
  // over it would cost far more.
  assert.equal(state.version, null);
  assert.equal(state.skippedVersion, null);
});

test('a file claiming an unknown shape is not trusted', async (t) => {
  const directory = await profile(t);
  await fs.promises.writeFile(
    path.join(directory, UPDATE_STATE_FILENAME),
    JSON.stringify({ schemaVersion: 99, automatic: true, version: '9.9.9' }),
  );

  // Nothing in it is believed, including the version it claims to have found.
  assert.equal((await readUpdateState(directory)).version, null);
});

test('a value of the wrong type is refused rather than written', async (t) => {
  const directory = await profile(t);

  await assert.rejects(
    writeUpdateState(directory, { automatic: 'yes' }),
    /invalid/,
  );
});
