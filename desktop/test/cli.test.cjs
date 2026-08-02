const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { CommandLine, CommandLineError, executablePath } = require('../src/cli.cjs');

const FAKE = path.join(__dirname, 'fake-cli.cjs');
fs.chmodSync(FAKE, 0o755);

// The stand-in is run directly, which needs an executable bit Windows has no
// equivalent for. The behaviour it covers is not platform-specific.
const windows = process.platform === 'win32';

function commandLine(mode = 'ok', log = []) {
  process.env.OMNIDECK_FAKE_CLI = mode;
  return new CommandLine({
    executable: FAKE,
    configDirectory: '/tmp/does-not-need-to-exist',
    instanceName: 'desktop',
    appendLog: async (line) => log.push(line),
  });
}

test('the bundled tool is found beside the application', () => {
  assert.equal(
    executablePath('/app/resources', 'darwin', {}),
    path.join('/app/resources', 'cli', 'omnideck'),
  );
  assert.equal(
    executablePath('C:\\app\\resources', 'win32', {}),
    path.join('C:\\app\\resources', 'cli', 'omnideck.exe'),
  );
  // So a checkout can drive a tool built from source.
  assert.equal(
    executablePath('/app/resources', 'linux', { OMNIDECK_CLI_PATH: '/built/omnideck' }),
    '/built/omnideck',
  );
});

test('a running installation answers with its status', { skip: windows }, async () => {
  const status = await commandLine('ok').status();

  assert.equal(status.status, 'running');
  assert.equal(status.webUiPort, '2338');
});

test('a stopped installation is an answer, not a failure', { skip: windows }, async () => {
  // The tool exits non-zero for anything not running, so the exit status
  // cannot be what decides whether there is an answer.
  const status = await commandLine('stopped').status();

  assert.equal(status.status, 'exited');
});

test('nothing installed reads as nothing installed', { skip: windows }, async () => {
  assert.equal(await commandLine('not-installed').status(), null);
});

test('a missing container is described, not treated as an absence', { skip: windows }, async () => {
  // Only the installation being absent reads as null. A missing container is
  // an installation that needs repairing, and saying so is the whole point.
  const status = await commandLine('no-container').status();

  assert.equal(status.status, 'unknown');
});

test('a failure carries the screen it belongs to', { skip: windows }, async () => {
  const cli = commandLine('no-engine');

  await assert.rejects(cli.start(), (error) => {
    assert.ok(error instanceof CommandLineError);
    assert.equal(error.code, 'ENGINE_NOT_FOUND');
    // A missing container runtime is a required-software problem, and the
    // screen that says so is the one that can install it.
    assert.equal(error.diagnostic, 'components');
    return true;
  });
});

test('a failure with no matching screen is left unclassified', { skip: windows }, async () => {
  const cli = commandLine('pull-fails');

  await assert.rejects(cli.create({ image: 'x', port: 1 }, () => {}), (error) => {
    assert.equal(error.code, 'INTERNAL_ERROR');
    // Better to say nothing about which step is at fault than to guess and
    // send someone to fix something that is fine.
    assert.equal(error.diagnostic, null);
    return true;
  });
});

test('creating reports each step against the phase it belongs to', { skip: windows }, async () => {
  const steps = [];
  const result = await commandLine('ok').create(
    { image: 'ghcr.io/omnideck-dev/omnideck@sha256:abc', port: 2338 },
    (step) => steps.push(step),
  );

  assert.deepEqual(
    steps.filter((step) => step.state === 'start').map((step) => [step.stage, step.phase]),
    [
      ['check_availability', 'download'],
      ['create_home_volume', 'download'],
      ['create_state_volume', 'download'],
      ['pull_image', 'download'],
      ['run_container', 'startup'],
      ['save_config', 'startup'],
    ],
  );
  // The download reports what it is doing while it does it, which is what the
  // wait needs to be filled with.
  assert.ok(steps.some((step) => step.state === 'progress' && step.detail));
  assert.deepEqual(result, { name: 'desktop', webUiPort: '2338' });
});

test('the completion is not reported as another step', { skip: windows }, async () => {
  const steps = [];
  await commandLine('ok').create({ image: 'x', port: 1 }, (step) => steps.push(step));

  assert.equal(steps.some((step) => step.stage === 'complete'), false);
});

test('output that is not json is ignored rather than fatal', { skip: windows }, async () => {
  const log = [];
  // The stand-in writes a stray line to stderr, as the real one does.
  const result = await commandLine('ok', log).create({ image: 'x', port: 1 }, () => {});

  assert.ok(result);
  assert.ok(log.some((line) => line.includes('not json')), 'it still reaches the log');
});

test('a tool that says nothing at all is a failure with a reason', { skip: windows }, async () => {
  await assert.rejects(commandLine('silent').start(), (error) => {
    assert.equal(error.code, 'INTERNAL_ERROR');
    assert.match(error.message, /something went very wrong/);
    return true;
  });
});

test('the next free browser port comes from the tool that knows what is taken', { skip: windows }, async () => {
  const defaults = await commandLine('ok').suggestedDefaults();

  assert.equal(defaults.webUiPort, '2339');
});

test('every call is written to the log with what it returned', { skip: windows }, async () => {
  const log = [];
  await commandLine('ok', log).status();

  assert.match(log[0], /^\$ omnideck status --name desktop \(0\)$/);
});
