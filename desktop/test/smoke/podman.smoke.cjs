// Checks the assumptions the runtime makes about the container tool against the
// real thing, rather than against a fake that agrees with them.
//
// Nothing here pulls an image or starts a container: every command either reads
// state or touches a throwaway volume, so the whole file runs in seconds. What
// it covers is the seam that fakes cannot — which stream output arrives on, and
// which exit codes mean "absent" rather than "broken".
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { OmniDeckRuntime } = require('../../src/runtime.cjs');

const SUITE = 'omnideck-podman-smoke';

async function runtimeWithPodman() {
  const userDataPath = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'omnideck-podman-'));
  const runtime = new OmniDeckRuntime({ userDataPath, onState: () => {} });
  runtime.podmanPath = await runtime.findExecutable('podman');
  return { runtime, userDataPath };
}

// Skipping is the honest outcome on a machine without podman. It is not an
// acceptable outcome in the job that installs podman on purpose, where a skip
// would quietly report success for tests that never ran.
const REQUIRED = process.env.OMNIDECK_SMOKE_REQUIRE_PODMAN === '1';

const available = (async () => {
  const { runtime } = await runtimeWithPodman();
  const found = Boolean(runtime.podmanPath);
  if (!found && REQUIRED) {
    throw new Error('podman was expected on this machine but could not be found');
  }
  return found;
})();

test('podman reports its version on stdout, not mixed into the transcript', async (t) => {
  const { runtime, userDataPath } = await runtimeWithPodman();
  t.after(() => fs.promises.rm(userDataPath, { recursive: true, force: true }));
  if (!await available) return t.skip('podman is not installed');

  const result = await runtime.run(
    runtime.podmanPath,
    ['info', '--format', '{{.Version.Version}}'],
    { label: 'runtime check' },
  );

  assert.equal(result.code, 0);
  // Warnings land on stderr and belong in the transcript, never in the value
  // the caller parses.
  assert.match(result.stdout.trim(), /^\d+\.\d+/, `unexpected stdout: ${result.stdout}`);
});

test('a container that does not exist reads as absent, not as a failure', async (t) => {
  const { runtime, userDataPath } = await runtimeWithPodman();
  t.after(() => fs.promises.rm(userDataPath, { recursive: true, force: true }));
  if (!await available) return t.skip('podman is not installed');
  runtime.containerName = `${SUITE}-missing-${process.pid}`;

  const info = await runtime.containerInfo();

  assert.equal(info, null, 'a missing container is a normal state, not an error');
});

test('podman explains a missing container without corrupting the value callers parse', async (t) => {
  const { runtime, userDataPath } = await runtimeWithPodman();
  t.after(() => fs.promises.rm(userDataPath, { recursive: true, force: true }));
  if (!await available) return t.skip('podman is not installed');

  const result = await runtime.run(
    runtime.podmanPath,
    ['container', 'inspect', `${SUITE}-missing-${process.pid}`],
    { label: 'app check', acceptExitCodes: [0, 125] },
  );

  assert.notEqual(result.code, 0);
  // A failed inspect still answers in JSON on stdout — an empty list — and puts
  // the explanation on stderr. A caller that parsed the transcript instead
  // would choke on prose that is not JSON at all.
  assert.deepEqual(JSON.parse(result.stdout), [], `unexpected stdout: ${result.stdout}`);
  assert.ok(
    result.output.length > result.stdout.length,
    'the explanation should reach the transcript without reaching stdout',
  );
});

test('volume existence is reported by exit status', async (t) => {
  const { runtime, userDataPath } = await runtimeWithPodman();
  t.after(() => fs.promises.rm(userDataPath, { recursive: true, force: true }));
  if (!await available) return t.skip('podman is not installed');

  const volume = `${SUITE}-${process.pid}`;
  t.after(async () => {
    await runtime.run(runtime.podmanPath, ['volume', 'rm', '--force', volume], {
      label: 'clean up', acceptAnyExitCode: true,
    }).catch(() => {});
  });

  const exists = (name) => runtime.run(
    runtime.podmanPath,
    ['volume', 'exists', name],
    { label: 'storage check', acceptExitCodes: [0, 1, 125] },
  );

  assert.notEqual((await exists(volume)).code, 0, 'a volume that was never created');
  await runtime.run(runtime.podmanPath, ['volume', 'create', volume], {
    label: 'prepare storage',
  });
  assert.equal((await exists(volume)).code, 0, 'the volume it just created');
});
