const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  removeOtherCliOutputs,
  targetForBuild,
  targetForHost,
} = require('../scripts/build-cli.cjs');
const {
  parseGoBuildSettings,
  verifyCliTarget,
} = require('../scripts/verify-cli-target.cjs');

test('CLI build targets use Go names for every supported desktop platform', () => {
  assert.deepEqual(targetForHost('win32', 'x64'), { goos: 'windows', goarch: 'amd64' });
  assert.deepEqual(targetForHost('darwin', 'arm64'), { goos: 'darwin', goarch: 'arm64' });
  assert.deepEqual(targetForHost('linux', 'x64'), { goos: 'linux', goarch: 'amd64' });
});

test('CLI build refuses an unsupported host instead of producing the wrong binary', () => {
  assert.throws(() => targetForHost('freebsd', 'x64'), /Unsupported CLI target/);
  assert.throws(() => targetForHost('linux', 'ia32'), /Unsupported CLI target architecture/);
});

test('cross-platform packages bundle the CLI for the package target, not the runner', () => {
  const targets = [
    ['windows', 'amd64'],
    ['windows', 'arm64'],
    ['darwin', 'amd64'],
    ['darwin', 'arm64'],
    ['linux', 'amd64'],
    ['linux', 'arm64'],
  ];
  for (const [goos, goarch] of targets) {
    assert.deepEqual(targetForBuild({
      platform: 'linux',
      arch: 'x64',
      env: { OMNIDECK_CLI_GOOS: goos, OMNIDECK_CLI_GOARCH: goarch },
    }), { goos, goarch });
  }
});

test('an incomplete explicit CLI target is rejected', () => {
  assert.throws(
    () => targetForBuild({ env: { OMNIDECK_CLI_GOOS: 'darwin' } }),
    /must be set together/,
  );
});

test('packaging verification reads the target embedded by Go', () => {
  assert.deepEqual(parseGoBuildSettings(`
    path github.com/omnideck-dev/cli
    build GOARCH=arm64
    build GOOS=linux
    build CGO_ENABLED=0
  `), { GOARCH: 'arm64', GOOS: 'linux', CGO_ENABLED: '0' });
});

test('CLI builds remove binaries left by another package target', (t) => {
  const runtimeRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'omnideck-cli-output-'));
  t.after(() => fs.rmSync(runtimeRoot, { recursive: true, force: true }));
  const unixCli = path.join(runtimeRoot, 'omnideck-cli');
  const windowsCli = path.join(runtimeRoot, 'omnideck-cli.exe');
  fs.writeFileSync(unixCli, 'linux');
  fs.writeFileSync(windowsCli, 'windows');

  removeOtherCliOutputs(runtimeRoot, windowsCli);

  assert.equal(fs.existsSync(unixCli), false);
  assert.equal(fs.readFileSync(windowsCli, 'utf8'), 'windows');
});

test('target verification rejects an extra CLI from another target', (t) => {
  const desktopRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'omnideck-cli-verify-'));
  t.after(() => fs.rmSync(desktopRoot, { recursive: true, force: true }));
  const runtimeRoot = path.join(desktopRoot, 'build', 'runtime');
  fs.mkdirSync(runtimeRoot, { recursive: true });
  fs.writeFileSync(path.join(runtimeRoot, 'omnideck-cli.exe'), 'windows');
  fs.writeFileSync(path.join(runtimeRoot, 'omnideck-cli'), 'linux');

  assert.throws(
    () => verifyCliTarget({
      desktopRoot,
      env: { OMNIDECK_CLI_GOOS: 'windows', OMNIDECK_CLI_GOARCH: 'amd64' },
    }),
    /CLI files for another target: omnideck-cli/,
  );
});
