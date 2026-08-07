// Exercises the packaged Desktop-to-CLI boundary against the actual bundled
// helper. This intentionally performs no install or container mutation.
const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { OmnideckRuntime } = require('../../src/runtime.cjs');

function runtime() {
  return new OmnideckRuntime({
    userDataPath: path.join(__dirname, '.smoke-user-data'),
    resourcesPath: path.join(__dirname, '..', '..', 'build'),
    onState: () => {},
  });
}

test('the bundled CLI reports the shared runtime contract', async () => {
  const status = await runtime().cliBackend.status();
  assert.equal(status.schemaVersion, 4);
  assert.equal(status.runtime, 'podman');
  assert.equal(typeof status.ready, 'boolean');
});

test('Desktop passes only a CLI executable to its process runner', async () => {
  const appRuntime = runtime();
  const executable = await appRuntime.cliBackend.requireExecutable();
  assert.match(path.basename(executable), /^omnideck-cli(?:\.exe)?$/);
});
