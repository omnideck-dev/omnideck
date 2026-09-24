import assert from 'node:assert/strict';
import test from 'node:test';

import {
  BUILD_TARGETS,
  classifyDesktopBuilds,
  githubOutput,
} from '../../.github/scripts/desktop-build-matrix.mjs';

const names = (result) => result.targets.map(({ name }) => name);

test('VM-lab and E2E harness changes skip native tests and package builds', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: [
      'desktop/scripts/run-linux-builder.sh',
      'desktop/scripts/run-windows-builder.sh',
      'desktop/tests/e2e/candidate-matrix.sh',
      'desktop/tests/manual/local-vm-lab.md',
    ],
  });
  assert.equal(result.buildRequired, false);
  assert.equal(result.nativeTestsRequired, false);
  assert.deepEqual(names(result), []);
});

test('Desktop documentation and release qualification changes skip packages', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: [
      '.github/workflows/desktop-hardware.yml',
      '.github/workflows/desktop-release-contract.yml',
      'desktop/TESTING.md',
      'desktop/scripts/release-test/windows.ps1',
      'docs/releases/v0.1.0-beta.11.md',
    ],
  });
  assert.equal(result.buildRequired, false);
  assert.deepEqual(names(result), []);
});

test('macOS packaging assets select only native macOS targets', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: ['desktop/src-tauri/assets/dmg-background.svg'],
  });
  assert.equal(result.buildRequired, true);
  assert.equal(result.fullMatrix, false);
  assert.deepEqual(names(result), ['macos-x64', 'macos-arm64']);
});

test('Windows packaging assets select only native Windows targets', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: ['desktop/src-tauri/icons/Square150x150Logo.png'],
  });
  assert.deepEqual(names(result), ['windows-x64', 'windows-arm64']);
});

test('multiple platform-only changes combine their target matrices', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: [
      'desktop/src-tauri/icons/icon.ico',
      'desktop/scripts/verify-macos-bundle.sh',
    ],
  });
  assert.deepEqual(names(result), [
    'windows-x64', 'windows-arm64', 'macos-x64', 'macos-arm64',
  ]);
});

test('product, dependency, runtime, and workflow changes retain the full matrix', () => {
  for (const path of [
    '.github/scripts/desktop-build-matrix.mjs',
    '.github/scripts/install-apt-packages.sh',
    '.github/workflows/desktop.yml',
    'desktop/container-version.txt',
    'desktop/pnpm-lock.yaml',
    'desktop/src-tauri/src/runtime.rs',
    'desktop/web/src/App.tsx',
  ]) {
    const result = classifyDesktopBuilds({ eventName: 'pull_request', paths: [path] });
    assert.equal(result.fullMatrix, true, path);
    assert.deepEqual(names(result), BUILD_TARGETS.map(({ name }) => name), path);
  }
});

test('pushes, tags, and manual runs always retain the full release matrix', () => {
  for (const [eventName, ref] of [
    ['push', 'refs/heads/main'],
    ['push', 'refs/tags/v0.1.0-beta.12'],
    ['workflow_dispatch', 'refs/heads/main'],
  ]) {
    const result = classifyDesktopBuilds({ eventName, ref, paths: [] });
    assert.equal(result.fullMatrix, true, `${eventName} ${ref}`);
    assert.equal(result.nativeTestsRequired, true, `${eventName} ${ref}`);
  }
});

test('a skipped build emits a parseable fallback matrix without requesting runners', () => {
  const result = classifyDesktopBuilds({
    eventName: 'pull_request',
    paths: ['desktop/tests/e2e/run.sh'],
  });
  const output = githubOutput(result);
  assert.match(output, /^build_required=false$/m);
  assert.match(output, /^native_tests_required=false$/m);
  const matrix = JSON.parse(output.match(/^matrix=(.+)$/m)[1]);
  assert.equal(matrix.include.length, BUILD_TARGETS.length);
});
