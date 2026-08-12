import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const run = await read('../tests/e2e/run.sh');
const windows = await read('../tests/e2e/run-windows.sh');
const windowsTrust = await read('../tests/e2e/windows_trust.ps1');
const windowsGuest = await read('../tests/e2e/windows_guest.ps1');
const linuxGuest = await read('../tests/e2e/linux_guest.sh');
const polkitAgent = await read('../tests/e2e/polkit_agent.py');
const driver = await read('../tests/e2e/webdriver_client.py');
const purge = await read('../tests/e2e/purge.sh');
const qualifier = await read('../tests/e2e/qualify-release.sh');
const releasePurge = await read('../tests/e2e/purge-release.sh');
const remainder = JSON.parse(await read('../tests/e2e/manual-remainder.json'));
const golden = JSON.parse(await read('../tests/e2e/golden-prerequisites.json'));

test('Desktop VM E2E uses the packaged app and frozen exact-copy mockup', () => {
  assert.match(run, /build-with-local-cli\.sh/);
  assert.match(run, /\/etc\/gdm\/custom\.conf/);
  assert.match(run, /restart display-manager/);
  assert.match(run, /WaylandEnable=false/);
  assert.match(linuxGuest, /WEBKIT_DISABLE_DMABUF_RENDERER/);
  assert.match(linuxGuest, /WEBKIT_DISABLE_COMPOSITING_MODE/);
  assert.doesNotMatch(linuxGuest, /LIBGL_ALWAYS_SOFTWARE/);
  assert.match(linuxGuest, /--appimage-extract/);
  assert.match(linuxGuest, /atomic-execution-boundary\.txt/);
  assert.match(linuxGuest, /cmp --silent/);
  assert.match(run, /target-scoped-pkttyagent/);
  assert.match(run, /polkit_agent\.py/);
  assert.match(linuxGuest, /auth-bin/);
  assert.match(linuxGuest, /\/usr\/bin\/pkexec "\\\$@"/);
  assert.match(linuxGuest, /--process "\\\$\\\$"/);
  assert.match(polkitAgent, /pkttyagent/);
  assert.match(polkitAgent, /disposable password supplied/);
  assert.match(windows, /build-with-local-cli-windows\.sh/);
  assert.match(windows, /windows_snapshots=/);
  assert.match(windows, /cancel-approve/);
  assert.match(windows, /RunOnceProof/);
  assert.match(windows, /LastBootUpTime/);
  assert.match(windows, /smartscreen-warning/);
  assert.match(windows, /warning-observed/);
  assert.match(windowsTrust, /UIAutomationClient/);
  assert.match(windowsTrust, /Start-Process -FilePath \(Join-Path \$env:WINDIR "explorer\.exe"\)/);
  assert.match(windowsTrust, /"More info"/);
  assert.match(windowsTrust, /"Run anyway"/);
  assert.match(windowsGuest, /F3017226-FE2A-4295-8BDF-00C3A9A7E4C5/);
  assert.match(windowsGuest, /does not match WebView2/);
  assert.match(windowsGuest, /"Driver"/);
  assert.match(windows, /phase_command Driver/);
  assert.match(driver, /tauri:options/);
  assert.match(driver, /mockup-parity/);
  assert.match(driver, /mockup-html/);
  assert.match(driver, /Uncontracted visible setup copy/);
  assert.match(driver, /EXPECTED_UPDATE_BRIDGE/);
  assert.match(driver, /update-bridge\.json/);
  assert.match(driver, /setup:updating/);
  assert.doesNotMatch(driver, /mockIPC|mock_invoke|dev server/i);
});

test('documented pnpm argument separators are accepted by both VM lanes', () => {
  assert.match(run, /--\) shift ;;/);
  assert.match(windows, /--\) shift ;;/);
});

test('Desktop VM evidence and destructive cleanup remain run-scoped', () => {
  assert.match(run, /artifacts\/desktop-e2e/);
  assert.match(windows, /artifacts\/desktop-e2e/);
  assert.match(run, /discarded-created\.txt/);
  assert.match(windows, /windows-tpm/);
  assert.match(purge, /dirname "\$\{run_dir\}"/);
  assert.match(purge, /run\.json/);
  assert.match(qualifier, /artifacts\/desktop-release/);
  assert.match(qualifier, /releasecontract\/verify-release\.mjs/);
  assert.match(qualifier, /gh attestation verify/);
  assert.match(qualifier, /appimage,deb,rpm,atomic,windows/);
  assert.match(releasePurge, /artifacts\/desktop-release/);
  assert.doesNotMatch(purge, /rm -rf/);
  assert.doesNotMatch(releasePurge, /rm -rf/);
});

test('manual-only behavior is explicit and never inferred as passed', () => {
  assert.equal(remainder.status, 'not-run');
  assert.match(remainder.rule, /never inferred/);
  assert.ok(remainder.procedures.length >= 5);
  assert.ok(remainder.procedures.some(({ covers }) => covers.includes('Gatekeeper')));
  assert.ok(remainder.procedures.some(({ covers }) => covers.includes('accessibility')));
});

test('golden prerequisites are versioned while exact drivers remain per-run', () => {
  assert.equal(golden.schemaVersion, 1);
  assert.equal(golden.recommendedBaseline, 'desktop-e2e-v2');
  assert.ok(golden.linux.checkpointInstall.some((item) => item.includes('WebKitWebDriver')));
  assert.ok(golden.windows.checkpointInstall.some((item) => item.includes('WebView2')));
  assert.ok(golden.managedPerRun.some((item) => item.includes('tauri-driver 2.0.6')));
  assert.ok(golden.managedPerRun.some((item) => item.includes('exact installed WebView2 version')));
  assert.ok(golden.managedPerRun.some((item) => item.includes('SmartScreen')));
  assert.match(run, /golden-prerequisites\.json/);
  assert.match(run, /recommended_baseline/);
  assert.match(run, /baseline="podman-ready"/);
  assert.match(windows, /golden-prerequisites\.json/);
});
