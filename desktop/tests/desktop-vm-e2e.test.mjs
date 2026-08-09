import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const run = await read('../tests/e2e/run.sh');
const windows = await read('../tests/e2e/run-windows.sh');
const driver = await read('../tests/e2e/webdriver_client.py');
const purge = await read('../tests/e2e/purge.sh');
const remainder = JSON.parse(await read('../tests/e2e/manual-remainder.json'));
const golden = JSON.parse(await read('../tests/e2e/golden-prerequisites.json'));

test('Desktop VM E2E uses the packaged app and frozen exact-copy mockup', () => {
  assert.match(run, /build-with-local-cli\.sh/);
  assert.match(windows, /build-with-local-cli-windows\.sh/);
  assert.match(driver, /tauri:options/);
  assert.match(driver, /mockup-parity/);
  assert.match(driver, /mockup-html/);
  assert.match(driver, /Uncontracted visible setup copy/);
  assert.match(driver, /EXPECTED_UPDATE_BRIDGE/);
  assert.match(driver, /update-bridge\.json/);
  assert.match(driver, /setup:updating/);
  assert.doesNotMatch(driver, /mockIPC|mock_invoke|dev server/i);
});

test('Desktop VM evidence and destructive cleanup remain run-scoped', () => {
  assert.match(run, /artifacts\/desktop-e2e/);
  assert.match(windows, /artifacts\/desktop-e2e/);
  assert.match(run, /discarded-created\.txt/);
  assert.match(windows, /windows-tpm/);
  assert.match(purge, /dirname "\$\{run_dir\}"/);
  assert.match(purge, /run\.json/);
  assert.doesNotMatch(purge, /rm -rf/);
});

test('manual-only behavior is explicit and never inferred as passed', () => {
  assert.equal(remainder.status, 'not-run');
  assert.match(remainder.rule, /never inferred/);
  assert.ok(remainder.procedures.length >= 5);
  assert.ok(remainder.procedures.some(({ covers }) => covers.includes('restart-now')));
  assert.ok(remainder.procedures.some(({ covers }) => covers.includes('accessibility')));
});

test('golden prerequisites are versioned while exact drivers remain per-run', () => {
  assert.equal(golden.schemaVersion, 1);
  assert.ok(golden.linux.checkpointInstall.some((item) => item.includes('WebKitWebDriver')));
  assert.ok(golden.windows.checkpointInstall.some((item) => item.includes('WebView2')));
  assert.ok(golden.managedPerRun.some((item) => item.includes('tauri-driver 2.0.6')));
  assert.ok(golden.managedPerRun.some((item) => item.includes('exact installed WebView2 version')));
  assert.match(run, /golden-prerequisites\.json/);
  assert.match(windows, /golden-prerequisites\.json/);
});
