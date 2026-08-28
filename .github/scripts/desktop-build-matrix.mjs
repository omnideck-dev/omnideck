#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

export const BUILD_TARGETS = Object.freeze([
  Object.freeze({
    name: 'linux-x64',
    platform: 'linux',
    runner: 'ubuntu-24.04',
    target: 'x86_64-unknown-linux-gnu',
    command: 'build:linux',
  }),
  Object.freeze({
    name: 'linux-arm64',
    platform: 'linux',
    runner: 'ubuntu-24.04-arm',
    target: 'aarch64-unknown-linux-gnu',
    command: 'build:linux:arm64',
  }),
  Object.freeze({
    name: 'windows-x64',
    platform: 'windows',
    runner: 'windows-2025',
    target: 'x86_64-pc-windows-msvc',
    command: 'build:windows',
  }),
  Object.freeze({
    name: 'windows-arm64',
    platform: 'windows',
    runner: 'windows-2025',
    target: 'aarch64-pc-windows-msvc',
    command: 'build:windows:arm64',
  }),
  Object.freeze({
    name: 'macos-x64',
    platform: 'macos',
    runner: 'macos-15-intel',
    target: 'x86_64-apple-darwin',
    command: 'build:macos:x64',
  }),
  Object.freeze({
    name: 'macos-arm64',
    platform: 'macos',
    runner: 'macos-15',
    target: 'aarch64-apple-darwin',
    command: 'build:macos',
  }),
]);

const TEST_ONLY_FILES = new Set([
  '.github/actionlint.yaml',
  '.github/workflows/desktop-hardware.yml',
  '.github/workflows/desktop-release-contract.yml',
  'desktop/scripts/build-with-local-cli-windows.sh',
  'desktop/scripts/build-with-local-cli.sh',
  'desktop/scripts/run-linux-builder.sh',
  'desktop/scripts/run-windows-builder.sh',
]);

function isWorkflowInput(path) {
  return path === '.github/actionlint.yaml'
    || path === '.github/scripts/desktop-build-matrix.mjs'
    || path === '.github/scripts/install-apt-packages.sh'
    || path === '.github/workflows/desktop.yml'
    || path === '.github/workflows/desktop-hardware.yml'
    || path === '.github/workflows/desktop-release-contract.yml'
    || path.startsWith('desktop/')
    || /^docs\/releases\/v[^/]+\.md$/.test(path);
}

function impactForPath(path) {
  if (!isWorkflowInput(path)) return null;
  if (TEST_ONLY_FILES.has(path)
    || path.startsWith('desktop/tests/')
    || path.startsWith('desktop/scripts/release-test/')
    || path.startsWith('docs/releases/')
    || (path.startsWith('desktop/') && path.endsWith('.md'))) {
    return 'none';
  }
  if (path.startsWith('desktop/src-tauri/assets/')
    || path === 'desktop/scripts/verify-macos-bundle.sh'
    || path === 'desktop/src-tauri/icons/icon.icns') {
    return 'macos';
  }
  if (path === 'desktop/src-tauri/icons/icon.ico'
    || /^desktop\/src-tauri\/icons\/(?:Square[^/]+|StoreLogo)\.png$/.test(path)) {
    return 'windows';
  }
  return 'all';
}

export function classifyDesktopBuilds({ eventName, ref = '', paths = [] }) {
  if (eventName !== 'pull_request') {
    return {
      buildRequired: true,
      fullMatrix: true,
      nativeTestsRequired: true,
      reason: ref.startsWith('refs/tags/') ? 'release tag' : `${eventName} event`,
      targets: [...BUILD_TARGETS],
    };
  }

  const impacts = paths.map(impactForPath).filter((impact) => impact !== null);
  if (impacts.includes('all')) {
    return {
      buildRequired: true,
      fullMatrix: true,
      nativeTestsRequired: true,
      reason: 'cross-platform product or packaging change',
      targets: [...BUILD_TARGETS],
    };
  }

  const platforms = new Set(impacts.filter((impact) => impact !== 'none'));
  const targets = BUILD_TARGETS.filter(({ platform }) => platforms.has(platform));
  if (targets.length > 0) {
    return {
      buildRequired: true,
      fullMatrix: false,
      nativeTestsRequired: true,
      reason: `${[...platforms].sort().join(', ')} packaging change`,
      targets,
    };
  }

  return {
    buildRequired: false,
    fullMatrix: false,
    nativeTestsRequired: false,
    reason: impacts.length > 0 ? 'test, VM-lab, or documentation change' : 'no Desktop workflow inputs changed',
    targets: [],
  };
}

function changedPaths(baseSha, headSha) {
  for (const [name, value] of [['base', baseSha], ['head', headSha]]) {
    if (!/^[a-f0-9]{40}$/.test(value)) {
      throw new Error(`A 40-character ${name} SHA is required for pull-request classification`);
    }
  }
  const output = execFileSync(
    'git',
    ['diff', '--name-only', '--no-renames', '-z', baseSha, headSha],
    { maxBuffer: 16 * 1024 * 1024 },
  );
  return output.toString('utf8').split('\0').filter(Boolean);
}

export function githubOutput(result) {
  // A skipped job still has its matrix expression parsed by Actions. Keep a
  // valid fallback matrix while build_required=false prevents runner use.
  const matrixTargets = result.targets.length > 0 ? result.targets : BUILD_TARGETS;
  return [
    `build_required=${result.buildRequired}`,
    `full_matrix=${result.fullMatrix}`,
    `native_tests_required=${result.nativeTestsRequired}`,
    `reason=${result.reason}`,
    `matrix=${JSON.stringify({ include: matrixTargets })}`,
  ].join('\n');
}

const invokedAsScript = process.argv[1]
  && pathToFileURL(process.argv[1]).href === import.meta.url;
if (invokedAsScript) {
  const eventName = process.env.DESKTOP_CI_EVENT_NAME ?? '';
  const ref = process.env.DESKTOP_CI_REF ?? '';
  const paths = eventName === 'pull_request'
    ? changedPaths(process.env.DESKTOP_CI_BASE_SHA ?? '', process.env.DESKTOP_CI_HEAD_SHA ?? '')
    : [];
  const result = classifyDesktopBuilds({ eventName, ref, paths });
  process.stdout.write(`${githubOutput(result)}\n`);
}
