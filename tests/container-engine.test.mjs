import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import {
  chmod,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const engineScript = join(repoRoot, 'scripts/container-engine.sh');
const justfile = await readFile(join(repoRoot, 'Justfile'), 'utf8');

const createFakeEngine = async (directory, name, version) => {
  const path = join(directory, name);
  await writeFile(
    path,
    `#!/bin/sh
if [ "\${1:-}" = "--version" ]; then
  printf '%s\\n' '${version}'
  exit 0
fi
if [ -n "\${CAPTURE_PATH:-}" ]; then
  printf 'BUILDX_BUILDER=%s|%s\\n' "\${BUILDX_BUILDER-<unset>}" "$*" >> "$CAPTURE_PATH"
fi
`,
  );
  await chmod(path, 0o755);
};

const runResolver = (directory, env = {}) =>
  spawnSync('/bin/bash', [engineScript, '--show'], {
    cwd: directory,
    encoding: 'utf8',
    env: { ...env, PATH: directory },
  });

test('auto-detects the only installed native engine', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));

  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');
  let result = runResolver(directory);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'podman');

  await rm(join(directory, 'podman'));
  await createFakeEngine(directory, 'docker', 'Docker version 28.0.0');
  result = runResolver(directory);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'docker');
});

test('recognizes the Docker compatibility shim as Podman', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));

  await createFakeEngine(directory, 'docker', 'podman version 5.4.0');
  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');

  const result = runResolver(directory);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'podman');
});

test('keeps Docker as the automatic default when both native engines exist', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));

  await createFakeEngine(directory, 'docker', 'Docker version 28.0.0');
  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');

  const result = runResolver(directory);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'docker');
});

test('environment override takes precedence over automatic selection', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));

  await createFakeEngine(directory, 'docker', 'Docker version 28.0.0');
  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');

  const result = runResolver(directory, { CONTAINER_ENGINE: 'podman' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'podman');
});

test('saved preference is repository-local and can return to auto detection', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');
  execFileSync('/usr/bin/git', ['init', '--quiet'], { cwd: directory });

  const env = { ...process.env, PATH: `${directory}:/usr/bin:/bin` };
  let result = spawnSync(
    '/bin/bash',
    [engineScript, '--select', 'podman'],
    { cwd: directory, encoding: 'utf8', env },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.equal(
    execFileSync('/usr/bin/git', ['config', '--local', '--get', 'omnideck.containerEngine'], {
      cwd: directory,
      encoding: 'utf8',
    }).trim(),
    'podman',
  );

  result = spawnSync('/bin/bash', [engineScript, '--select', 'auto'], {
    cwd: directory,
    encoding: 'utf8',
    env,
  });
  assert.equal(result.status, 0, result.stderr);
  const preference = spawnSync(
    '/usr/bin/git',
    ['config', '--local', '--get', 'omnideck.containerEngine'],
    { cwd: directory, encoding: 'utf8' },
  );
  assert.equal(preference.status, 1);
});

test('local builds use native engine commands without Buildx loading', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-engine-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const capturePath = join(directory, 'capture.txt');
  await createFakeEngine(directory, 'docker', 'Docker version 28.0.0');
  await createFakeEngine(directory, 'podman', 'podman version 5.4.0');
  const path = `${directory}:${process.env.PATH}`;
  const dockerEnv = {
    ...process.env,
    BUILDX_BUILDER: 'remote-builder',
    CAPTURE_PATH: capturePath,
    CONTAINER_ENGINE: 'docker',
    PATH: path,
  };

  const resolved = spawnSync('/bin/bash', [engineScript, '--show'], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: dockerEnv,
  });
  assert.equal(resolved.status, 0, resolved.stderr);
  assert.equal(resolved.stdout.trim(), 'docker');

  let result = spawnSync('just', ['_build-image', 'omnideck:test-docker'], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: dockerEnv,
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  let captured = await readFile(capturePath, 'utf8');
  assert.match(captured, /BUILDX_BUILDER=<unset>\|build -f container\/Dockerfile/);
  assert.doesNotMatch(captured, /--load|buildx/);

  await writeFile(capturePath, '');
  result = spawnSync('just', ['_build-image', 'omnideck:test-podman'], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: {
      ...process.env,
      CAPTURE_PATH: capturePath,
      CONTAINER_ENGINE: 'podman',
      PATH: path,
    },
  });
  assert.equal(result.status, 0, result.stderr);
  captured = await readFile(capturePath, 'utf8');
  assert.match(captured, /build -f container\/Dockerfile/);
  assert.doesNotMatch(captured, /--load|buildx/);
});

test('Justfile keeps local publishing out and relabels every state bind mount', () => {
  assert.doesNotMatch(justfile, /^publish(?:\s|:)/m);
  assert.doesNotMatch(justfile, /docker buildx/);
  assert.equal([...justfile.matchAll(/:rw,z/g)].length, 6);
  assert.match(justfile, /E2E_SKIP_BUILD/);
});
