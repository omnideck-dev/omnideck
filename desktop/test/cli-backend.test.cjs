const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const {
  OmnideckCliBackend,
  resolveCliPath,
  validateRuntimeStatus,
} = require('../src/cli-backend.cjs');

const READY = {
  schemaVersion: 4,
  runtime: 'podman',
  state: 'ready',
  ready: true,
  machineName: 'omnideck-runtime',
  phase: 'environment',
  activity: 'Preparing a secure space to run in…',
  resources: {
    container: { memory: '4g', shmSize: '2048m' },
    machine: { mode: 'wsl-managed' },
  },
};

test('CLI resolution prefers an explicit development binary', async () => {
  const explicit = path.resolve('custom', 'omnideck-cli.exe');
  const checked = [];
  const found = await resolveCliPath({
    resourcesPath: path.resolve('resources'),
    platform: 'win32',
    env: { OMNIDECK_CLI_PATH: explicit },
    access: async (candidate) => {
      checked.push(candidate);
      if (candidate !== explicit) throw new Error('missing');
    },
  });

  assert.equal(found, explicit);
  assert.deepEqual(checked, [explicit]);
});

test('runtime status uses the versioned Podman-only JSON contract', async () => {
  const calls = [];
  const backend = new OmnideckCliBackend({
    resourcesPath: '/resources',
    platform: 'linux',
    env: { OMNIDECK_CLI_PATH: __filename },
    run: async (executable, args, options) => {
      calls.push({ executable, args, options });
      return { stdout: JSON.stringify(READY), output: JSON.stringify(READY), code: 0 };
    },
  });

  assert.deepEqual(await backend.status(), READY);
  assert.deepEqual(calls[0].args, ['--json', 'runtime', 'status']);
  assert.equal(calls[0].options.label, 'shared runtime status');
});

test('runtime ensure forwards progress and returns the completed status', async () => {
  const seen = [];
  const onInactivity = () => {};
  const lines = [
    { stage: 'software', state: 'start', activity: 'Getting your computer ready…' },
    { stage: 'software', state: 'progress', detail: 'Installing Podman', progress: 0.5 },
    { stage: 'software', state: 'done', activity: 'Getting your computer ready…' },
    { stage: 'environment', state: 'start', activity: 'Preparing a secure space to run in…' },
    { stage: 'complete', state: 'done', result: READY },
  ];
  const backend = new OmnideckCliBackend({
    resourcesPath: '/resources',
    platform: 'linux',
    env: { OMNIDECK_CLI_PATH: __filename },
    run: async (_executable, args, options) => {
      assert.deepEqual(args, ['--json', 'runtime', 'ensure']);
      assert.equal(options.inactivityMs, 90_000);
      assert.equal(options.onInactivity, onInactivity);
      for (const line of lines) options.onLine(JSON.stringify(line));
      return { stdout: lines.map(JSON.stringify).join('\n'), output: '', code: 0 };
    },
  });

  assert.deepEqual(await backend.ensure({
    onEvent: (event) => seen.push(event.stage),
    onInactivity,
  }), READY);
  assert.deepEqual(seen, lines.map((line) => line.stage));
});

test('application status and start are delegated to named CLI commands', async () => {
  const status = {
    container: 'omnideck-desktop',
    status: 'running',
    image: 'ghcr.io/omnideck-dev/omnideck@sha256:test',
    webUiPort: '2338',
  };
  const calls = [];
  const backend = new OmnideckCliBackend({
    resourcesPath: '/resources',
    platform: 'linux',
    env: { OMNIDECK_CLI_PATH: __filename },
    run: async (_executable, args) => {
      calls.push(args);
      return { stdout: JSON.stringify(status), output: JSON.stringify(status), code: 0 };
    },
  });

  assert.deepEqual(await backend.instanceStatus('omnideck-desktop'), status);
  assert.deepEqual(await backend.startInstance('omnideck-desktop'), status);
  assert.deepEqual(calls, [
    ['--json', '--name', 'omnideck-desktop', 'status'],
    ['--json', '--name', 'omnideck-desktop', 'start'],
  ]);
});

test('environment reconciliation passes the complete desired state to the CLI', async () => {
  const status = {
    container: 'omnideck-desktop',
    status: 'running',
    image: 'ghcr.io/omnideck-dev/omnideck@sha256:test',
    webUiPort: '24444',
  };
  const complete = {
    stage: 'complete',
    state: 'done',
    result: { changed: true, action: 'created', status },
  };
  let command;
  const backend = new OmnideckCliBackend({
    resourcesPath: '/resources',
    platform: 'linux',
    env: { OMNIDECK_CLI_PATH: __filename },
    run: async (_executable, args, options) => {
      command = args;
      options.onLine(JSON.stringify({ stage: 'pull_image', state: 'progress', detail: 'layer' }));
      options.onLine(JSON.stringify(complete));
      return { stdout: JSON.stringify(complete), output: '', code: 0 };
    },
  });

  const result = await backend.ensureEnvironment({
    name: 'omnideck-desktop',
    image: status.image,
    port: 24444,
    memory: '4g',
    shmSize: '2048m',
    homeVolume: 'omnideck-desktop-home',
    stateVolume: 'omnideck-desktop-state',
  });

  assert.deepEqual(result, complete.result);
  assert.deepEqual(command, [
    '--json', '--name', 'omnideck-desktop',
    'environment', 'ensure',
    '--image', status.image,
    '--port', '24444',
    '--memory', '4g',
    '--shm-size', '2048m',
    '--home-volume', 'omnideck-desktop-home',
    '--state-volume', 'omnideck-desktop-state',
  ]);
});

test('an incompatible runtime contract is rejected', () => {
  assert.throws(
    () => validateRuntimeStatus({ ...READY, schemaVersion: 1 }),
    /expected 4/,
  );
});

test('runtime status requires the shared resource policy', () => {
  assert.throws(
    () => validateRuntimeStatus({ ...READY, resources: undefined }),
    /invalid resource defaults/,
  );
});

test('runtime status rejects shared memory larger than the container limit', () => {
  assert.throws(
    () => validateRuntimeStatus({
      ...READY,
      resources: {
        container: { memory: '2g', shmSize: '3g' },
        machine: { mode: 'wsl-managed' },
      },
    }),
    /incompatible container resource defaults/,
  );
});

test('macOS runtime status requires two GiB of VM headroom', () => {
  assert.doesNotThrow(() => validateRuntimeStatus({
    ...READY,
    resources: {
      container: { memory: '4g', shmSize: '2048m' },
      machine: { mode: 'podman-managed', memoryMB: 6144 },
    },
  }));
  assert.throws(
    () => validateRuntimeStatus({
      ...READY,
      resources: {
        container: { memory: '4g', shmSize: '2048m' },
        machine: { mode: 'podman-managed', memoryMB: 4096 },
      },
    }),
    /machine memory limit that is too small/,
  );
});
