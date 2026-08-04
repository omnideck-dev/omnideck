const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  configDirectory,
  instanceDocument,
  instancePath,
  publishInstance,
} = require('../src/cli-instance.cjs');

const DETAILS = {
  containerName: 'omnideck-desktop',
  homeVolume: 'omnideck-desktop-home',
  stateVolume: 'omnideck-desktop-state',
  port: 2338,
  image: `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`,
  installedAt: '2026-08-01T00:00:00.000Z',
};

test('each operating system is looked in where it keeps configuration', () => {
  const home = os.homedir();

  assert.equal(
    configDirectory('linux', { XDG_CONFIG_HOME: '/xdg' }),
    path.join('/xdg', 'omnideck-cli'),
  );
  assert.equal(
    configDirectory('linux', {}),
    path.join(home, '.config', 'omnideck-cli'),
  );
  assert.equal(
    configDirectory('darwin', {}),
    path.join(home, 'Library', 'Application Support', 'omnideck-cli'),
  );
  assert.equal(
    configDirectory('win32', { APPDATA: 'C:\\Users\\a\\AppData\\Roaming' }),
    path.join('C:\\Users\\a\\AppData\\Roaming', 'omnideck-cli'),
  );
});

test('an explicit configuration directory wins on every platform', () => {
  for (const platform of ['linux', 'darwin', 'win32']) {
    assert.equal(
      configDirectory(platform, { OMNIDECK_CONFIG_DIR: path.resolve('/elsewhere') }),
      path.resolve('/elsewhere'),
    );
  }
});

test('the file lands beside the ones the command line tool set up itself', () => {
  const written = instancePath('linux', { XDG_CONFIG_HOME: '/xdg' });

  assert.equal(written, path.join('/xdg', 'omnideck-cli', 'instances', 'desktop.yaml'));
});

test('the document carries what the command line tool reads', () => {
  const document = instanceDocument(DETAILS);

  assert.match(document, /^container_name: omnideck-desktop$/m);
  assert.match(document, /^home_volume: omnideck-desktop-home$/m);
  assert.match(document, /^state_volume: omnideck-desktop-state$/m);
  assert.match(document, /^image: ghcr\.io\/omnideck-dev\/omnideck@sha256:a{64}$/m);
  // Quoted, because the port is read as text and an unquoted number is not.
  assert.match(document, /^web_ui_port: "2338"$/m);
});

test('the file says it is not the place to edit', () => {
  // It is rewritten on every start, so an edit made here would vanish without
  // explanation.
  assert.match(instanceDocument(DETAILS), /^# Written by the omnideck application/);
});

test('publishing creates the directory and the file', async (t) => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-cli-'));
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }));

  const written = await publishInstance(DETAILS, 'linux', { OMNIDECK_CONFIG_DIR: root });

  assert.equal(written, path.join(root, 'instances', 'desktop.yaml'));
  assert.match(await fs.promises.readFile(written, 'utf8'), /container_name: omnideck-desktop/);
});

test('publishing twice replaces rather than accumulates', async (t) => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-cli-'));
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }));
  await publishInstance(DETAILS, 'linux', { OMNIDECK_CONFIG_DIR: root });

  await publishInstance({ ...DETAILS, port: 2400 }, 'linux', { OMNIDECK_CONFIG_DIR: root });

  const contents = await fs.promises.readFile(
    path.join(root, 'instances', 'desktop.yaml'),
    'utf8',
  );
  assert.match(contents, /^web_ui_port: "2400"$/m);
  assert.deepEqual(await fs.promises.readdir(path.join(root, 'instances')), ['desktop.yaml']);
});

test('a directory that cannot be written is not a reason to fail', async (t) => {
  const root = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-cli-'));
  t.after(() => fs.promises.rm(root, { recursive: true, force: true }));
  // A file where the directory needs to be: writing cannot succeed.
  await fs.promises.writeFile(path.join(root, 'instances'), 'not a directory');

  const written = await publishInstance(DETAILS, 'linux', { OMNIDECK_CONFIG_DIR: root });

  assert.equal(written, null, 'omnideck starts regardless of what the other tool has');
});
