import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const run = await read('../tests/e2e/run.sh');
const windows = await read('../tests/e2e/run-windows.sh');
const linuxBuilder = await read('../scripts/run-linux-builder.sh');
const windowsBuilder = await read('../scripts/run-windows-builder.sh');
const windowsTrust = await read('../tests/e2e/windows_trust.ps1');
const windowsGuest = await read('../tests/e2e/windows_guest.ps1');
const windowsStartDriver = await read('../tests/e2e/windows_start_driver.ps1');
const linuxGuest = await read('../tests/e2e/linux_guest.sh');
const polkitAgent = await read('../tests/e2e/polkit_agent.py');
const driver = await read('../tests/e2e/webdriver_client.py');
const customAppFixture = await read('../tests/e2e/custom_app_fixture.py');
const hostBoundaryDriver = await read('../tests/e2e/host_boundary_client.py');
const purge = await read('../tests/e2e/purge.sh');
const qualifier = await read('../tests/e2e/qualify-release.sh');
const releasePurge = await read('../tests/e2e/purge-release.sh');
const packageSmoke = await read('../tests/e2e/run-package-smoke.sh');
const packageSmokeGuest = await read('../tests/e2e/linux_package_smoke.sh');
const smokeMatrix = await read('../tests/e2e/smoke-matrix.sh');
const smokeMatrixGuest = await read('../tests/e2e/smoke-matrix-guest.sh');
const smokeMatrixReportUrl = new URL('../tests/e2e/smoke_matrix_report.py', import.meta.url);
const packageSmokePurge = await read('../tests/e2e/purge-package-smoke.sh');
const remainder = JSON.parse(await read('../tests/e2e/manual-remainder.json'));
const golden = JSON.parse(await read('../tests/e2e/golden-prerequisites.json'));

test('Desktop VM E2E uses the packaged app and frozen exact-copy mockup', () => {
  assert.match(run, /build-with-local-cli\.sh/);
  assert.match(run, /\/etc\/gdm3\/daemon\.conf/);
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
  assert.match(run, /OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR/);
  assert.match(windows, /OMNIDECK_DESKTOP_BUILD_OUTPUT_DIR/);
  assert.match(linuxBuilder, /CARGO_TARGET_DIR=\/out/);
  assert.match(windowsBuilder, /CARGO_TARGET_DIR=\/out/);
  assert.doesNotMatch(run, /desktop_root\}\/src-tauri\/target/);
  assert.doesNotMatch(windows, /desktop_root\}\/src-tauri\/target/);
  assert.match(windows, /windows_snapshots=/);
  assert.match(windows, /cancel-approve/);
  assert.match(windows, /RunOnceProof/);
  assert.match(windows, /phase_command PatchRunOnce/);
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
  assert.match(run, /custom_app_fixture\.py/);
  assert.match(linuxGuest, /run_journey custom-app/);
  assert.match(windows, /phase_command CustomAppFixture/);
  assert.match(windows, /run_journey custom-app/);
  assert.match(windowsGuest, /"CustomAppFixture"/);
  assert.match(windowsStartDriver, /ToLowerInvariant\(\)/);
  assert.match(windowsStartDriver, /replace '\[\^a-z0-9-\]'/);
  assert.match(windowsStartDriver, /Length -gt 40/);
  assert.match(windowsGuest, /\$ContainerName = "omnideck-desktop-\$TestNamespace"/);
  assert.match(windowsGuest, /\$HomeVolume = "omnideck-desktop-home-\$TestNamespace"/);
  assert.match(windowsGuest, /\$StateVolume = "omnideck-desktop-state-\$TestNamespace"/);
  assert.match(windowsGuest, /\$MachineName = "omnideck-runtime"/);
  assert.match(windowsGuest, /"PatchRunOnce"/);
  assert.match(windowsGuest, /windows_resume\.ps1/);
  assert.match(
    windowsGuest,
    /SetEnvironmentVariable\("OMNIDECK_DESKTOP_TEST_NAMESPACE", \$TestNamespace, "User"\)/,
  );
  assert.match(windowsGuest, /"OMNIDECK_DESKTOP_UPDATE_FIXTURE"/);
  assert.match(windows, /for attempt in \$\(seq 1 480\)/);
  assert.match(windows, /attempt % 10 == 0/);
  assert.match(windowsGuest, /os\.environ\['E2E_ARTIFACT_FILENAME'\]/);
  assert.doesNotMatch(windowsGuest, /os\.environ\["E2E_ARTIFACT_FILENAME"\]/);
  assert.match(driver, /CUSTOM_APP_STATE_SCRIPT/);
  assert.match(driver, /invoked-after-restart/);
  assert.match(driver, /desktopSmokeLastAttempt/);
  assert.match(driver, /button && bridgeAvailable/);
  assert.match(customAppFixture, /Desktop Custom App Smoke/);
  assert.match(customAppFixture, /window\.omnideck\.invoke/);
  assert.match(run, /host_boundary_client\.py/);
  assert.match(windows, /host_boundary_client\.py/);
  assert.match(linuxGuest, /native host download/);
  assert.match(linuxGuest, /native host upload/);
  assert.match(linuxGuest, /native artifact download/);
  assert.match(linuxGuest, /native zoom bridge/);
  assert.match(linuxGuest, /native update bridge/);
  assert.match(linuxGuest, /OMNIDECK_DESKTOP_UPDATE_FIXTURE/);
  assert.match(windowsGuest, /HostBoundaryDownload/);
  assert.match(windowsGuest, /HostBoundaryArtifactDownload/);
  assert.match(windowsGuest, /SeedUpdateFixture/);
  assert.match(windows, /-FixtureName \\\"\$\{fixture_name\}\\\"/);
  assert.match(hostBoundaryDriver, /send_keys/);
  assert.match(hostBoundaryDriver, /Export navigated the hosted application/);
  assert.match(hostBoundaryDriver, /Download complete/);
  assert.match(hostBoundaryDriver, /artifact_download/);
  assert.match(hostBoundaryDriver, /new KeyboardEvent\('keydown'/);
  assert.match(hostBoundaryDriver, /new WheelEvent\('wheel'/);
  assert.match(hostBoundaryDriver, /keyboardPageZoomApplied/);
  assert.match(hostBoundaryDriver, /wheelPageZoomApplied/);
  assert.match(hostBoundaryDriver, /window\.__omnideckDesktopZoom/);
  assert.match(hostBoundaryDriver, /document\.documentElement\.style\.zoom/);
  assert.match(hostBoundaryDriver, /trustedWheelZoom/);
  assert.match(hostBoundaryDriver, /windowactivate/);
  assert.match(hostBoundaryDriver, /windowfocus/);
  assert.match(hostBoundaryDriver, /getwindowgeometry/);
  assert.match(hostBoundaryDriver, /center_x/);
  assert.match(linuxGuest, /--native-input-tool/);
  assert.match(linuxGuest, /"\$\{operation\}" == "zoom" && "\$\{ID\}" == "ubuntu"/);
  assert.match(hostBoundaryDriver, /checkForUpdate/);
  assert.match(hostBoundaryDriver, /error\?\.message/);
  assert.doesNotMatch(hostBoundaryDriver, /mockIPC|mock_invoke|dev server/i);
  assert.doesNotMatch(driver, /mockIPC|mock_invoke|dev server/i);
  assert.doesNotMatch(customAppFixture, /mockIPC|mock_invoke|dev server/i);
  assert.ok(
    windows.indexOf('phase_command SeedUpdateFixture')
      < windows.indexOf('start_driver skip'),
    'the Windows update fixture must exist before the first app launch',
  );
  assert.ok(
    windows.indexOf('phase_command PromoteUpdateFixture')
      < windows.indexOf('run_host_boundary update-bridge'),
    'the Windows update fixture must become newer immediately before its bridge journey',
  );
});

test('documented pnpm argument separators are accepted by both VM lanes', () => {
  assert.match(run, /--\) shift ;;/);
  assert.match(windows, /--\) shift ;;/);
});

test('Desktop VM evidence and destructive cleanup remain run-scoped', () => {
  assert.match(run, /artifact-path desktop e2e/);
  assert.match(windows, /artifact-path desktop e2e/);
  assert.match(run, /evidence-init/);
  assert.match(windows, /evidence-finish/);
  assert.match(run, /qualification_complete=0/);
  assert.match(run, /stopped before its evidence was validated/);
  assert.match(run, /qualification_complete=1/);
  assert.match(windows, /qualification_complete=0/);
  assert.match(windows, /stopped before its evidence was validated/);
  assert.match(windows, /qualification_complete=1/);
  assert.match(purge, /runs purge/);
  assert.match(qualifier, /artifact-path desktop release/);
  assert.match(qualifier, /releasecontract\/verify-release\.mjs/);
  assert.match(qualifier, /gh attestation verify/);
  assert.match(qualifier, /appimage,deb,rpm,atomic,windows/);
  assert.match(qualifier, /--cross-distro-smoke/);
  assert.match(qualifier, /smoke-matrix\.sh/);
  assert.match(releasePurge, /runs purge/);
  assert.match(packageSmokePurge, /runs purge/);
  assert.match(run, /lease "\$\{vm\}" desktop/);
  assert.match(windows, /lease windows desktop/);
  assert.match(packageSmoke, /lease "\$\{vm\}" desktop-smoke/);
  assert.doesNotMatch(run, /omnideck-cli-vm-e2e|discarded-before/);
  assert.doesNotMatch(windows, /omnideck-desktop-vm-e2e|discarded-before/);
  assert.doesNotMatch(packageSmoke, /omnideck-cli-vm-e2e|discarded-before/);
  assert.doesNotMatch(purge, /rm -rf/);
  assert.doesNotMatch(releasePurge, /rm -rf/);
  assert.doesNotMatch(packageSmokePurge, /rm -rf/);
});

test('cross-distro smoke separates the guest from the package format', () => {
  assert.match(packageSmoke, /--vm appimage\|deb\|rpm\|atomic/);
  assert.match(packageSmoke, /--package appimage\|deb\|rpm\|flatpak/);
  assert.match(packageSmoke, /linux_package_smoke\.sh/);
  assert.doesNotMatch(packageSmoke, /tauri-driver|webdriver_client/);
  assert.match(packageSmokeGuest, /rpm2cpio/);
  assert.match(packageSmokeGuest, /flatpak install --user --noninteractive/);
  assert.match(packageSmokeGuest, /OMNIDECK_DESKTOP_SMOKE_FILE/);
  assert.match(packageSmokeGuest, /\["--version", "--json runtime status"\]/);
  assert.match(smokeMatrix, /appimage:appimage\|deb:deb\|rpm:rpm\|atomic:appimage/);
  assert.match(smokeMatrix, /for package_kind in appimage deb rpm flatpak/);
  assert.match(smokeMatrix, /finish_incomplete_matrix/);
  assert.match(smokeMatrix, /evidence_status=canceled/);
  assert.match(smokeMatrix, /lease "\$\{vm\}" desktop-smoke-matrix/);
  assert.match(smokeMatrixGuest, /OMNIDECK_DESKTOP_VM_SMOKE_REUSE_GUEST=1/);
  assert.match(smokeMatrixGuest, /Preparing %s once/);
});

test('cross-distro smoke report retains every cell and fails the aggregate', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-smoke-matrix-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const statusFile = join(directory, 'status.tsv');
  await writeFile(
    statusFile,
    'appimage\trpm\tpassed\tcells/appimage-rpm\topened\n' +
      'rpm\tdeb\tfailed\tcells/rpm-deb\texited 1\n',
  );
  const result = spawnSync(
    'python3',
    [
      smokeMatrixReportUrl.pathname,
      '--status-file',
      statusFile,
      '--output',
      directory,
      '--run-id',
      'test-run',
      '--started-at',
      '2026-01-01T00:00:00Z',
    ],
    { encoding: 'utf8' },
  );
  assert.equal(result.status, 1, result.stderr);
  const summary = JSON.parse(await readFile(join(directory, 'summary.json'), 'utf8'));
  assert.equal(summary.status, 'failed');
  assert.deepEqual(
    summary.cells.map(({ guest, package: packageKind, status }) => ({
      guest,
      package: packageKind,
      status,
    })),
    [
      { guest: 'appimage', package: 'rpm', status: 'passed' },
      { guest: 'rpm', package: 'deb', status: 'failed' },
    ],
  );
  assert.match(await readFile(join(directory, 'junit.xml'), 'utf8'), /failures="1"/);
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
  assert.match(run, /lab\.sh" profile/);
  assert.match(run, /lab\.sh" preflight/);
  assert.match(run, /lab\.sh" describe/);
  assert.match(windows, /golden-prerequisites\.json/);
  assert.match(windows, /lab\.sh" profile/);
  assert.match(windows, /lab\.sh" preflight/);
  assert.match(run, /--cleanup-baseline clean/);
  assert.match(windows, /--cleanup-baseline clean/);
});

test('current Linux guests install only the input dependencies their lane uses', () => {
  assert.match(linuxGuest, /apt-get install -y -qq webkit2gtk-driver xdotool/);
  assert.match(linuxGuest, /dnf install -y webkitgtk6\.0/);
  assert.doesNotMatch(linuxGuest, /dnf install -y webkitgtk6\.0 xdotool/);
  assert.match(JSON.stringify(golden), /xdotool installed per-run.*Ubuntu/);
});

test('host-boundary journeys retry only transient WebDriver disconnects', () => {
  assert.match(linuxGuest, /for attempt in 1 2 3/);
  assert.match(
    linuxGuest,
    /WebDriverError:\.\*\(Remote end closed\|Connection reset\|Connection refused\)/,
  );
  assert.match(linuxGuest, /transient-failure-attempt-/);
});

test('the updater bridge fixture is newer than the bundled runtime image', async () => {
  const fixtureVersion = linuxGuest.match(/update_version="([^"]+)"/)?.[1];
  const imageVersion = JSON.parse(
    await read('../src-tauri/resources/image-manifest.json'),
  ).imageVersion;
  assert.ok(fixtureVersion);
  assert.ok(
    fixtureVersion.localeCompare(imageVersion, undefined, { numeric: true }) > 0,
    `${fixtureVersion} must be newer than ${imageVersion}`,
  );
  assert.match(linuxGuest, /--expected-update-version "\$\{update_version\}"/);
  assert.match(windowsGuest, /version = "0\.1\.5"/);
});
