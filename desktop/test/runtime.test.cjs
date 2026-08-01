const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  APP_VERSION,
  SETUP_PHASES,
  FAILURE_COPY,
  IMAGE,
  IMAGE_REF_LABEL,
  OmniDeckRuntime,
  SETUP_COPY,
  installerUrl,
  linuxInstallCommands,
  parseOsRelease,
  replaceDownloadedFile,
  reserveAvailablePort,
  sha256File,
  testResourceNames,
} = require('../src/runtime.cjs');
const {
  readSetupState,
  writeSetupState,
} = require('../src/setup-state.cjs');

async function runtimeFixture(context, digestCharacter = 'a') {
  const resourcesPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-runtime-test-'));
  context.after(() => fs.rm(resourcesPath, { recursive: true, force: true }));
  const runtimePath = path.join(resourcesPath, 'runtime');
  const userDataPath = path.join(resourcesPath, 'user-data');
  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${digestCharacter.repeat(64)}`;
  await fs.mkdir(runtimePath);
  await fs.writeFile(
    path.join(runtimePath, 'image-manifest.json'),
    `${JSON.stringify({
      schemaVersion: 2,
      appVersion: APP_VERSION,
      imageRef,
    })}\n`,
  );
  return { imageRef, resourcesPath, runtimePath, userDataPath };
}

// Shapes a fake `podman container inspect` the way run() reports one: the JSON
// payload on stdout, and the transcript carrying podman's stderr chatter too.
function inspectResult(container, stderrNoise = '') {
  const payload = JSON.stringify([container]);
  return {
    code: 0,
    stdout: payload,
    output: stderrNoise ? `${stderrNoise}\n${payload}` : payload,
  };
}

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

test('interrupted setup reuses a verified completed download', async (context) => {
  const downloadRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-download-test-'));
  context.after(() => fs.rm(downloadRoot, { recursive: true, force: true }));
  const destination = path.join(downloadRoot, 'podman-installer.pkg');
  await fs.writeFile(destination, 'verified cached installer');
  const digest = await sha256File(destination);
  const previousFetch = global.fetch;
  context.after(() => {
    global.fetch = previousFetch;
  });
  global.fetch = async () => {
    throw new Error('A verified cached download must not be fetched again.');
  };
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(downloadRoot, 'user-data'),
    onState: () => {},
  });

  await runtime.download('https://example.invalid/installer.pkg', destination, digest);

  assert.equal(await fs.readFile(destination, 'utf8'), 'verified cached installer');
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

test('test resources are isolated behind a validated namespace', () => {
  assert.deepEqual(testResourceNames('release-test'), {
    container: 'omnideck-desktop-release-test',
    homeVolume: 'omnideck-desktop-home-release-test',
    stateVolume: 'omnideck-desktop-state-release-test',
    machine: 'omnideck-runtime-release-test',
  });
  assert.throws(() => testResourceNames('../unsafe'), /only lowercase/);
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
  runtime.ensureImage = async () => {};
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

test('release image manifest pins an immutable image digest', async (context) => {
  const resourcesPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-image-test-'));
  context.after(() => fs.rm(resourcesPath, { recursive: true, force: true }));
  const runtimePath = path.join(resourcesPath, 'runtime');
  await fs.mkdir(runtimePath);
  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`;
  await fs.writeFile(
    path.join(runtimePath, 'image-manifest.json'),
    `${JSON.stringify({
      schemaVersion: 2,
      appVersion: APP_VERSION,
      imageRef,
    })}\n`,
  );

  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(resourcesPath, 'user-data'),
    resourcesPath,
    onState: () => {},
  });
  const releaseImage = await runtime.releaseImage();

  assert.equal(releaseImage.appVersion, APP_VERSION);
  assert.equal(releaseImage.imageRef, imageRef);
});

test('first setup pulls the pinned release image and tags it locally', async (context) => {
  const resourcesPath = await fs.mkdtemp(path.join(os.tmpdir(), 'omnideck-pull-test-'));
  context.after(() => fs.rm(resourcesPath, { recursive: true, force: true }));
  const runtimePath = path.join(resourcesPath, 'runtime');
  await fs.mkdir(runtimePath);
  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'b'.repeat(64)}`;
  await fs.writeFile(
    path.join(runtimePath, 'image-manifest.json'),
    `${JSON.stringify({
      schemaVersion: 2,
      appVersion: APP_VERSION,
      imageRef,
    })}\n`,
  );

  const calls = [];
  const states = [];
  let pulled = false;
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(resourcesPath, 'user-data'),
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.podmanPath = 'podman';
  runtime.run = async (_executable, args) => {
    calls.push(args);
    if (args[0] === 'image' && args[1] === 'exists') {
      return { code: pulled ? 0 : 1, output: '' };
    }
    if (args[0] === 'pull') pulled = true;
    return { code: 0, output: '' };
  };

  await runtime.ensureImage();

  assert.ok(calls.some((args) => args[0] === 'pull' && args.at(-1) === imageRef));
  assert.ok(calls.some((args) => (
    args[0] === 'tag' && args[1] === imageRef && args[2] === IMAGE
  )));
  assert.ok(states.some((state) => (
    state.stage === 'preparing'
    && state.title === 'Preparing your environment'
    && state.indeterminate
  )));
  assert.ok(!calls.some((args) => args[0] === 'load'));
});

test('a packaged release refuses a missing runtime image manifest', async () => {
  const runtime = new OmniDeckRuntime({
    userDataPath: path.join(path.sep, 'tmp', 'omnideck-test'),
    onState: () => {},
  });
  runtime.podmanPath = 'podman';
  runtime.releaseImage = async () => null;

  await assert.rejects(
    runtime.ensureImage(),
    /does not identify its application image/,
  );
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

  const imageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'c'.repeat(64)}`;
  runtime.currentEnvironment = { imageRef, sourceImage: imageRef };
  assert.equal(runtime.isCurrentContainer({
    Config: {
      Image: 'localhost/omnideck/runtime:an-older-wrapper',
      Labels: {
        'dev.omnideck.version': '0.1.0-alpha.0',
        [IMAGE_REF_LABEL]: imageRef,
      },
    },
  }), true);
});

test('a new installation shows Welcome without running environment checks', async (context) => {
  const { resourcesPath, userDataPath } = await runtimeFixture(context);
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.findExecutable = async () => {
    throw new Error('New installations must not check before Welcome.');
  };

  const result = await runtime.startExisting();

  assert.deepEqual(result, { action: 'welcome', reason: 'first-run' });
  assert.equal(states.at(-1).title, 'Welcome to omnideck');
  assert.equal(states.at(-1).canStart, true);
});

test('interrupted setup resumes automatically without a separate resume screen', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context);
  await writeSetupState(userDataPath, {
    status: 'in-progress',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef,
  });
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });

  const result = await runtime.startExisting();

  assert.deepEqual(result, { action: 'setup', reason: 'resume' });
  assert.equal(states.at(-1).title, 'Preparing your environment');
  assert.equal(states.at(-1).indeterminate, true);
  assert.ok(!states.some((state) => /continue|finish setting up/i.test(state.title)));
});

test('a changed pinned image selects the update flow', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, 'd');
  const oldImageRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'e'.repeat(64)}`;
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: '0.1.0-alpha.0',
    imageRef: oldImageRef,
  });
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };

  const result = await runtime.startExisting();

  assert.deepEqual(result, { action: 'setup', reason: 'update' });
  assert.equal(states.at(-1).setupReason, 'update');
  assert.match(states.at(-1).detail, /Bringing omnideck up to date/);
  assert.notEqual(imageRef, oldImageRef);
});

test('a legacy desktop container without setup state migrates through update', async (context) => {
  const { resourcesPath, userDataPath } = await runtimeFixture(context, '4');
  await fs.mkdir(path.join(userDataPath, 'runtime'), { recursive: true });
  await fs.writeFile(path.join(userDataPath, 'runtime', 'app-port'), '2337\n');
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.findExecutable = async () => 'podman';
  runtime.run = async (_executable, args) => {
    if (args[0] === 'container') {
      return inspectResult({
        Config: {
          Image: 'localhost/omnideck/runtime:0.1.0-alpha.3',
          Labels: { 'dev.omnideck.version': '0.1.0-alpha.3' },
        },
        State: { Status: 'running' },
      });
    }
    return { code: 0, output: '', stdout: '' };
  };

  const result = await runtime.startExisting();

  assert.deepEqual(result, { action: 'setup', reason: 'update' });
  assert.equal(states.at(-1).setupReason, 'update');
});

test('a healthy completed setup with the same digest opens directly', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, 'f');
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: '0.1.0-alpha.0',
    imageRef,
  });
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };
  runtime.findExecutable = async () => 'podman';
  runtime.run = async (_executable, args) => {
    if (args[0] === 'container') {
      return inspectResult({
        Config: {
          Image: 'localhost/omnideck/runtime:older-wrapper',
          Labels: { [IMAGE_REF_LABEL]: imageRef },
        },
        State: { Status: 'running' },
      });
    }
    return { code: 0, output: '', stdout: '' };
  };
  let waitedSilently = false;
  runtime.waitForApp = async (options) => {
    waitedSilently = options.silent;
  };

  const result = await runtime.startExisting();

  assert.equal(result.action, 'open');
  assert.equal(waitedSilently, true);
  assert.equal(states.length, 0);
  const migrated = await readSetupState(userDataPath);
  assert.equal(migrated.appVersion, APP_VERSION);
  assert.equal(migrated.imageRef, imageRef);
});

test('an unhealthy existing install reports which phase failed', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '1');
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef,
  });
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };
  runtime.findExecutable = async () => 'podman';
  runtime.run = async (_executable, args) => {
    if (args[0] === 'container') return { code: 125, output: '', stdout: '' };
    return { code: 0, output: '', stdout: '' };
  };

  const result = await runtime.startExisting();
  const doctor = states.at(-1);

  assert.equal(result.action, 'doctor');
  assert.equal(doctor.stage, 'error');
  assert.equal(doctor.diagnostics.find((item) => item.id === 'startup').status, 'issue');
  assert.equal(doctor.canRetry, true);
});

test('a damaged installer blames no phase, because none had started', async (context) => {
  const { resourcesPath, runtimePath, userDataPath } = await runtimeFixture(context, '3');
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef: `ghcr.io/omnideck-dev/omnideck@sha256:${'3'.repeat(64)}`,
  });
  await fs.writeFile(path.join(runtimePath, 'image-manifest.json'), '{"schemaVersion":1}\n');
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });

  const result = await runtime.startExisting();
  const doctor = states.at(-1);

  assert.equal(result.action, 'doctor');
  assert.equal(doctor.primaryAction, 'download');
  assert.ok(
    !doctor.diagnostics.some((item) => item.status !== 'waiting'),
    'no phase had started, so none should be marked',
  );
});

test('setup remains resumable after failure and becomes complete only when ready', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '2');
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.findExecutable = async () => 'podman';
  runtime.ensureRuntimeReady = async () => {
    throw new Error('runtime unavailable');
  };

  await assert.rejects(runtime.setup('first-run'), /runtime unavailable/);
  const interrupted = await readSetupState(userDataPath);
  assert.equal(interrupted.status, 'in-progress');
  assert.equal(interrupted.imageRef, imageRef);

  runtime.ensureRuntimeReady = async () => {};
  runtime.ensureContainer = async () => {};
  runtime.waitForApp = async () => {};
  await runtime.setup('resume');

  const complete = await readSetupState(userDataPath);
  assert.equal(complete.status, 'complete');
  assert.equal(states.at(-1).stage, 'ready');
  assert.equal(states.at(-1).title, 'omnideck is ready');
});

test('podman warnings on stderr do not corrupt container inspection', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '5');
  const runtime = new OmniDeckRuntime({ userDataPath, resourcesPath, onState: () => {} });
  runtime.podmanPath = 'podman';
  runtime.currentEnvironment = { imageRef, sourceImage: imageRef };
  runtime.run = async () => inspectResult(
    {
      Config: { Image: IMAGE, Labels: { [IMAGE_REF_LABEL]: imageRef } },
      State: { Status: 'running' },
    },
    'WARN[0000] Failed to add pause process to systemd sandbox cgroup',
  );

  const info = await runtime.containerInfo();

  assert.equal(info.State.Status, 'running');
  assert.equal(runtime.isCurrentContainer(info), true);
});

test('a tagged failure keeps its phase when the transcript mentions downloads', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  const error = new Error('start app exited with code 125');
  error.diagnostic = 'startup';
  error.failureKind = 'startup';
  error.output = 'Trying to pull ghcr.io/...\nerror: connection reset while reading http response';

  runtime.reportFailure(error);
  const reported = states.at(-1);

  assert.equal(reported.diagnosticResult, 'Startup issue');
  assert.equal(reported.diagnostics.find((item) => item.id === 'startup').status, 'issue');
  assert.equal(reported.diagnostics.find((item) => item.id === 'download').status, 'pass');
  assert.equal(reported.canRetry, true);
});

test('an unsupported computer keeps its guidance when the message says restart', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  const error = new Error('omnideck cannot restart the required component on this computer.');
  error.diagnostic = 'support';
  error.failureKind = 'support';

  runtime.reportFailure(error);
  const reported = states.at(-1);

  assert.equal(reported.diagnosticResult, 'Compatibility issue');
  assert.equal(reported.primaryAction, 'supported-systems');
  assert.equal(reported.canRetry, false);
});

test('a damaged release still offers a fresh download', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  const error = new Error('The omnideck runtime image manifest is invalid.');
  error.diagnostic = 'release';
  error.failureKind = 'release';

  runtime.reportFailure(error);

  assert.equal(states.at(-1).primaryAction, 'download');
  assert.equal(states.at(-1).primaryLabel, 'Download omnideck');
  assert.equal(states.at(-1).canRetry, false);
});

test('a declined authorization prompt is reported as a permission issue', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  const error = new Error('system installer exited with code 1');
  error.diagnostic = 'components';
  error.failureKind = 'permission';
  error.output = 'User canceled.';

  runtime.reportFailure(error);

  assert.equal(states.at(-1).diagnosticResult, 'Permission needed');
  assert.equal(states.at(-1).canRetry, true);
});

test('an untagged failure is still classified from its message', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });

  runtime.reportFailure(new Error('the network connection was lost'));

  assert.equal(states.at(-1).diagnosticResult, 'Download issue');
});

test('chunk progress is rate limited and advances the overall bar', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  runtime.beginPhase('download');
  const atPhaseStart = states.at(-1).progress;

  for (let index = 0; index < 2_000; index += 1) {
    runtime.emitProgressUpdate(index / 2_000);
  }

  assert.ok(states.length < 20, `expected a throttled stream, got ${states.length} emits`);
  assert.ok(states.every((state) => state.progress >= 0 && state.progress <= 1));
  // The emits are throttled, so the advance is read from the runtime rather
  // than from what reached the screen inside a single throttle window.
  assert.ok(runtime.overallProgress() > atPhaseStart, 'the bar should have advanced');
  assert.ok(runtime.overallProgress() < 1, 'a mid-phase download is not the whole of setup');
});

test('progress without a known total stays indeterminate', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });

  runtime.emitProgressUpdate();

  assert.equal(states.at(-1).progress, null);
  assert.equal(states.at(-1).indeterminate, true);
});

test('a host port taken while omnideck was closed is exchanged for a free one', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '6');
  const runtime = new OmniDeckRuntime({ userDataPath, resourcesPath, onState: () => {} });
  runtime.podmanPath = 'podman';
  runtime.currentEnvironment = { imageRef, sourceImage: imageRef };
  await runtime.prepare();
  const originalPort = runtime.appPort;

  runtime.run = async (_executable, args) => {
    if (args[0] === 'start') {
      const error = new Error('start app exited with code 125');
      error.output = 'rootlessport cannot expose 127.0.0.1:2337: address already in use';
      throw error;
    }
    return { code: 0, output: '', stdout: '' };
  };

  const started = await runtime.startCurrentContainer({ State: { Status: 'exited' } });

  assert.equal(started, false, 'the container must be rebuilt rather than started again');
  assert.notEqual(runtime.appPort, originalPort);
  const persisted = await fs.readFile(path.join(userDataPath, 'runtime', 'app-port'), 'utf8');
  assert.equal(Number.parseInt(persisted, 10), runtime.appPort);
});

test('an unrelated start failure is not mistaken for a port conflict', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '7');
  const runtime = new OmniDeckRuntime({ userDataPath, resourcesPath, onState: () => {} });
  runtime.podmanPath = 'podman';
  runtime.currentEnvironment = { imageRef, sourceImage: imageRef };
  await runtime.prepare();
  runtime.run = async () => {
    const error = new Error('start app exited with code 125');
    error.output = 'Error: no such container';
    throw error;
  };

  await assert.rejects(
    runtime.startCurrentContainer({ State: { Status: 'exited' } }),
    /exited with code 125/,
  );
});

test('a reachable container skips the separate runtime probe', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '8');
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef,
  });
  const runtime = new OmniDeckRuntime({ userDataPath, resourcesPath, onState: () => {} });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };
  runtime.findExecutable = async () => 'podman';
  runtime.waitForApp = async () => {};
  const calls = [];
  runtime.run = async (_executable, args) => {
    calls.push(args);
    if (args[0] === 'container') {
      return inspectResult({
        Config: { Image: IMAGE, Labels: { [IMAGE_REF_LABEL]: imageRef } },
        State: { Status: 'running' },
      });
    }
    return { code: 0, output: '', stdout: '' };
  };

  const result = await runtime.startExisting();

  assert.equal(result.action, 'open');
  assert.ok(
    !calls.some((args) => args[0] === 'info'),
    'container state already proves the runtime is reachable',
  );
});

test('a missing container still falls back to probing the runtime', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, '9');
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef,
  });
  const runtime = new OmniDeckRuntime({ userDataPath, resourcesPath, onState: () => {} });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };
  runtime.findExecutable = async () => 'podman';
  const calls = [];
  runtime.run = async (_executable, args) => {
    calls.push(args);
    if (args[0] === 'container') return { code: 125, output: '', stdout: '' };
    return { code: 0, output: '', stdout: '' };
  };

  await runtime.startExisting();

  assert.ok(calls.some((args) => args[0] === 'info'), 'an absent container needs the probe');
});

test('phases run in order and weigh the whole of setup', () => {
  assert.deepEqual(
    SETUP_PHASES.map(({ id }) => id),
    ['software', 'environment', 'download', 'startup'],
  );
  const download = SETUP_PHASES.find((phase) => phase.id === 'download');
  const others = SETUP_PHASES.filter((phase) => phase.id !== 'download');
  assert.ok(
    download.weight >= others.reduce((sum, phase) => sum + phase.weight, 0) / 2,
    'the download is most of the wait and should own most of the bar',
  );
});

test('setup copy names no component, except where consent needs specifics', () => {
  const forbidden = /podman|docker|container|image|wsl|windows subsystem|volume|machine|registry/i;
  for (const phase of SETUP_PHASES) {
    assert.ok(!forbidden.test(`${phase.label} ${phase.activity}`), phase.activity);
  }
  // The two permission screens are the exception: they are where an
  // administrator prompt is approved, and consent needs to name what it is for.
  const consent = ['permission', 'permissionWindows'];
  for (const [key, copy] of Object.entries(SETUP_COPY)) {
    if (consent.includes(key)) continue;
    assert.ok(!forbidden.test(`${copy.title} ${copy.detail}`), copy.title);
  }
  for (const copy of Object.values(FAILURE_COPY)) {
    assert.ok(!forbidden.test(`${copy.title} ${copy.detail}`), copy.title);
  }
  assert.match(SETUP_COPY.permission.detail, /Podman/);
});

test('setup reports what it is doing, one activity at a time', async (context) => {
  const { resourcesPath, userDataPath } = await runtimeFixture(context, 'b');
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.findExecutable = async () => 'podman';
  runtime.ensureRuntimeReady = async () => {};
  runtime.ensureContainer = async () => {};
  runtime.waitForApp = async () => {};

  await runtime.setup('first-run');

  const activities = [...new Set(states.map((state) => state.activity).filter(Boolean))];
  assert.deepEqual(
    activities,
    runtime.phases.map((phase) => phase.activity),
    'every applicable phase should announce itself, in order',
  );
  assert.ok(
    !states.some((state) => state.stage === 'preparing' && state.diagnostics),
    'no checklist is shown while setup is working',
  );
  assert.equal(states.at(-1).stage, 'ready');
  assert.equal(states.at(-1).progress, 1);
});

test('a phase that does not apply to this computer is not counted', () => {
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: () => {} });
  // The runtime picks its own phases from the host platform; drive both shapes
  // explicitly so the weighting is checked on Linux and elsewhere alike.
  runtime.phases = SETUP_PHASES.filter((phase) => phase.id !== 'environment');
  runtime.phaseIndex = runtime.phases.length - 1;
  runtime.phaseFraction = 1;

  assert.equal(runtime.overallProgress(), 1, 'the bar must still reach full');
});

test('a resumed setup says earlier work was kept without adding a screen', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });
  runtime.setupReason = 'resume';

  runtime.emitWorking();
  const resumed = states.at(-1);

  assert.match(resumed.detail, /Continuing from where the last attempt stopped/);
  assert.equal(resumed.canStart, false, 'resuming must not wait for a click');
  assert.equal(resumed.title, 'Preparing your environment');
});

test('a healthy install opens without mentioning a newer image', async (context) => {
  const { imageRef, resourcesPath, userDataPath } = await runtimeFixture(context, 'c');
  const staleRef = `ghcr.io/omnideck-dev/omnideck@sha256:${'b'.repeat(64)}`;
  await writeSetupState(userDataPath, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageRef: staleRef,
  });
  const states = [];
  const runtime = new OmniDeckRuntime({
    userDataPath,
    resourcesPath,
    onState: (state) => states.push(state),
  });
  runtime.prepare = async () => {
    runtime.appPort = 2337;
  };
  runtime.findExecutable = async () => 'podman';
  runtime.waitForApp = async () => {};
  runtime.run = async (_executable, args) => {
    if (args[0] === 'container') {
      // The container matches the installed version, not the newer one.
      return inspectResult({
        Config: { Image: IMAGE, Labels: { [IMAGE_REF_LABEL]: staleRef } },
        State: { Status: 'running' },
      });
    }
    return { code: 0, output: '', stdout: '' };
  };

  const result = await runtime.startExisting();

  assert.equal(result.action, 'open', 'opening must never be interrupted by an update');
  assert.equal(states.length, 0, 'no screen should be shown on the way to the app');
  assert.notEqual(imageRef, staleRef);
});

test('an unclassified failure does not accuse a checkpoint', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });

  runtime.reportFailure(new Error('something entirely unexpected happened'));
  const reported = states.at(-1);

  assert.equal(reported.diagnosticResult, 'Setup issue');
  assert.ok(
    !reported.diagnostics.some((item) => item.status === 'issue'),
    'no checkpoint should be blamed for a failure nobody classified',
  );
});

test('every failure kind offers a way forward and its own title', () => {
  const titles = new Set();
  for (const [kind, copy] of Object.entries(FAILURE_COPY)) {
    assert.ok(copy.canRetry || copy.primaryAction, `${kind} leaves the person stuck`);
    assert.ok(!titles.has(copy.title), `${kind} repeats the title "${copy.title}"`);
    titles.add(copy.title);
  }
});

test('the failure screen offers the diagnostic log as its secondary action', () => {
  const states = [];
  const runtime = new OmniDeckRuntime({ userDataPath: '/nonexistent', onState: (s) => states.push(s) });

  runtime.reportFailure(new Error('anything'));

  assert.equal(states.at(-1).secondaryAction, 'show-logs');
  assert.equal(states.at(-1).secondaryLabel, 'Show diagnostic log');
});
