const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  APP_VERSION,
  IMAGE,
  OmniDeckRuntime,
  installerUrl,
  linuxInstallCommands,
  parseOsRelease,
  replaceDownloadedFile,
  reserveAvailablePort,
} = require('../src/runtime.cjs');

test('parseOsRelease accepts quoted and unquoted values', () => {
  assert.deepEqual(
    parseOsRelease('ID="ubuntu"\nVERSION_ID=24.04\n'),
    { ID: 'ubuntu', VERSION_ID: '24.04' },
  );
});

test('Ubuntu setup installs Podman without using a shell', () => {
  const commands = linuxInstallCommands('ubuntu', (name) => `/usr/bin/${name}`);
  assert.deepEqual(commands, [
    ['/usr/bin/apt-get', ['update']],
    ['/usr/bin/apt-get', ['install', '-y', 'podman']],
  ]);
});

test('unknown Linux distributions do not guess an installer', () => {
  assert.deepEqual(linuxInstallCommands('unknown', (name) => name), []);
});

test('installer URL is pinned to the reviewed Podman release', () => {
  assert.equal(
    installerUrl('podman-installer-windows-amd64.msi'),
    'https://github.com/podman-container-tools/podman/releases/download/v6.0.2/podman-installer-windows-amd64.msi',
  );
});

test('a fresh runtime download replaces a file left by a failed setup', async (context) => {
  const downloadRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-download-test-'));
  context.after(() => fs.rm(downloadRoot, { recursive: true, force: true }));
  const destination = path.join(downloadRoot, 'podman-installer.msi');
  const partial = `${destination}.partial`;
  await fs.writeFile(destination, 'stale download');
  await fs.writeFile(partial, 'fresh verified download');

  await replaceDownloadedFile(partial, destination);

  assert.equal(await fs.readFile(destination, 'utf8'), 'fresh verified download');
  await assert.rejects(fs.access(partial), { code: 'ENOENT' });
});

test('Windows installer verification passes the path through the child environment', async () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });
  const destination = String.raw`C:\Users\Test User\AppData\Roaming\OmniDeck\downloads\podman.msi`;
  let invocation;
  runtime.findExecutable = async () => 'powershell.exe';
  runtime.run = async (executable, args, options) => {
    invocation = { executable, args, options };
    return { code: 0, output: '' };
  };

  await runtime.verifyWindowsInstaller(destination);

  assert.equal(invocation.executable, 'powershell.exe');
  assert.deepEqual(invocation.args.slice(0, 4), [
    '-NoLogo',
    '-NoProfile',
    '-NonInteractive',
    '-Command',
  ]);
  assert.equal(invocation.args.length, 5);
  assert.match(invocation.args[4], /\$env:OMNIDECK_INSTALLER_PATH/);
  assert.ok(!invocation.args.includes(destination));
  assert.equal(invocation.options.env.OMNIDECK_INSTALLER_PATH, destination);
  assert.equal(invocation.options.label, 'verify installer');
});

test('Windows WSL elevation passes the executable path through the child environment', async () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });
  const wsl = String.raw`C:\Windows\System32\wsl.exe`;
  const calls = [];
  runtime.findExecutable = async (name) => {
    if (name === 'wsl.exe') return wsl;
    if (name === 'powershell.exe') return 'powershell.exe';
    return null;
  };
  runtime.run = async (executable, args, options) => {
    calls.push({ executable, args, options });
    if (executable === wsl && args[0] === '--status') {
      const statusChecks = calls.filter((call) => (
        call.executable === wsl && call.args[0] === '--status'
      ));
      return { code: statusChecks.length === 1 ? 1 : 0, output: '' };
    }
    return { code: 0, output: '' };
  };

  await runtime.ensureWindowsPrerequisites();

  const elevation = calls.find((call) => call.options.label === 'Windows workspace setup');
  assert.ok(elevation);
  assert.equal(elevation.executable, 'powershell.exe');
  assert.equal(elevation.args.length, 5);
  assert.match(elevation.args[4], /\$env:OMNIDECK_WSL_PATH/);
  assert.ok(!elevation.args.includes(wsl));
  assert.equal(elevation.options.env.OMNIDECK_WSL_PATH, wsl);
});

test('runtime state stays under the desktop application data directory', () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });
  const env = runtime.runtimeEnv();

  assert.equal(
    env.XDG_CONFIG_HOME,
    path.join(path.sep, 'tmp', 'omnideck-test', 'runtime', 'config'),
  );
  assert.equal(
    env.XDG_DATA_HOME,
    path.join(path.sep, 'tmp', 'omnideck-test', 'runtime', 'data'),
  );
  assert.equal(
    env.REGISTRY_AUTH_FILE,
    path.join(path.sep, 'tmp', 'omnideck-test', 'runtime', 'auth', 'auth.json'),
  );
});

test('runtime selects another loopback port when the preferred port is occupied', async () => {
  const occupied = net.createServer();
  await new Promise((resolve) => occupied.listen(0, '127.0.0.1', resolve));
  const occupiedPort = occupied.address().port;

  try {
    const selectedPort = await reserveAvailablePort(occupiedPort);
    assert.notEqual(selectedPort, occupiedPort);
    assert.ok(selectedPort > 0 && selectedPort <= 65535);
  } finally {
    await new Promise((resolve) => occupied.close(resolve));
  }
});

test('new app container exposes only the loopback web port and disables the legacy desktop', async () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });
  const calls = [];
  runtime.podmanPath = 'podman';
  runtime.appPort = 24444;
  runtime.run = async (_executable, args) => {
    calls.push(args);
    if (args[0] === 'container' && args[1] === 'inspect') return { code: 125, output: '' };
    if (args[0] === 'volume' && args[1] === 'inspect') return { code: 125, output: '' };
    return { code: 0, output: '' };
  };

  await runtime.ensureContainer();

  const runArgs = calls.find((args) => args[0] === 'run');
  assert.ok(runArgs);
  assert.ok(runArgs.includes('127.0.0.1:24444:8080'));
  assert.ok(runArgs.includes('ENABLE_DESKTOP=false'));
  assert.ok(runArgs.includes(`dev.omnideck.version=${APP_VERSION}`));
  assert.ok(runArgs.includes('k8s-file'));
  assert.ok(runArgs.includes('max-size=150mb'));
  assert.equal(runArgs.at(-1), IMAGE);
  assert.ok(!runArgs.some((argument) => argument.includes('6080') || argument.includes('5900')));
});

test('bundled image manifest must match the app version and architecture', async (context) => {
  const resourcesPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-bundle-test-'));
  context.after(() => fs.rm(resourcesPath, { recursive: true, force: true }));
  const runtimePath = path.join(resourcesPath, 'runtime');
  await fs.mkdir(runtimePath);
  const archivePath = path.join(runtimePath, 'omnideck-image.oci.tar');
  const contents = Buffer.from('test OCI archive');
  await fs.writeFile(archivePath, contents);
  await fs.writeFile(
    path.join(runtimePath, 'image-manifest.json'),
    `${JSON.stringify({
      schemaVersion: 1,
      appVersion: APP_VERSION,
      architecture: process.arch === 'x64' ? 'amd64' : process.arch,
      imageRef: IMAGE,
      archive: path.basename(archivePath),
      archiveSha256: crypto.createHash('sha256').update(contents).digest('hex'),
    })}\n`,
  );

  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(resourcesPath, 'user-data'),
    resourcesPath,
    onState: () => {},
  });
  const bundle = await runtime.bundledImage();

  assert.equal(bundle.archivePath, archivePath);
  assert.equal(bundle.appVersion, APP_VERSION);
  assert.equal(bundle.imageRef, IMAGE);
});

test('first setup loads the bundled image instead of pulling a registry image', async (context) => {
  const resourcesPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-load-test-'));
  context.after(() => fs.rm(resourcesPath, { recursive: true, force: true }));
  const runtimePath = path.join(resourcesPath, 'runtime');
  await fs.mkdir(runtimePath);
  const archivePath = path.join(runtimePath, 'omnideck-image.oci.tar');
  const contents = Buffer.from('small test OCI archive');
  await fs.writeFile(archivePath, contents);
  await fs.writeFile(
    path.join(runtimePath, 'image-manifest.json'),
    `${JSON.stringify({
      schemaVersion: 1,
      appVersion: APP_VERSION,
      architecture: process.arch === 'x64' ? 'amd64' : process.arch,
      imageRef: IMAGE,
      archive: path.basename(archivePath),
      archiveSha256: crypto.createHash('sha256').update(contents).digest('hex'),
    })}\n`,
  );

  const calls = [];
  let loaded = false;
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(resourcesPath, 'user-data'),
    resourcesPath,
    onState: () => {},
  });
  runtime.podmanPath = 'podman';
  runtime.run = async (_executable, args) => {
    calls.push(args);
    if (args[0] === 'image' && args[1] === 'exists') {
      return { code: loaded ? 0 : 1, output: '' };
    }
    if (args[0] === 'load') loaded = true;
    return { code: 0, output: '' };
  };

  await runtime.ensureImage();

  assert.ok(calls.some((args) => args[0] === 'load' && args.at(-1) === archivePath));
  assert.ok(!calls.some((args) => args[0] === 'pull'));
});

test('an existing container is current only when both version label and image match', () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });

  assert.equal(runtime.isCurrentContainer({
    Config: {
      Image: IMAGE,
      Labels: { 'dev.omnideck.version': APP_VERSION },
    },
  }), true);
  assert.equal(runtime.isCurrentContainer({
    Config: {
      Image: 'ghcr.io/omnideck-dev/omnideck:latest',
      Labels: {},
    },
  }), false);
});
