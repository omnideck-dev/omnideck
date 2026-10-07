import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const run = await read('../tests/e2e/run.sh');
const windows = await read('../tests/e2e/run-windows.sh');
const macos = await read('../tests/e2e/run-macos-lab.sh');
const macosGuest = await read('../tests/e2e/macos_accessibility_guest.sh');
const linuxBuilder = await read('../scripts/run-linux-builder.sh');
const windowsBuilder = await read('../scripts/run-windows-builder.sh');
const windowsBuilderDockerfile = await read('../containers/windows-builder/Dockerfile');
const windowsTrust = await read('../tests/e2e/windows_trust.ps1');
const windowsGuest = await read('../tests/e2e/windows_guest.ps1');
const windowsStartDriver = await read('../tests/e2e/windows_start_driver.ps1');
const linuxGuest = await read('../tests/e2e/linux_guest.sh');

test('macOS lane refuses a running ordinary app without terminating it', { skip: process.platform !== 'linux' }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-macos-process-guard-'));
  const guard = macosGuest.split("current_step='exclusive desktop process'\n")[1].split('\nif [[ "$upgrade_dmg" != none ]]')[0];
  for (const executable of ['omnideck-desktop', 'omnideck']) {
    const ordinary = spawn('bash', ['-c', 'exec -a "$1" sleep 60', 'fixture', `/Applications/ordinary.app/Contents/MacOS/${executable}`]);
    try {
      await new Promise((resolve, reject) => {
        ordinary.once('spawn', resolve);
        ordinary.once('error', reject);
      });
      const result = spawnSync('bash', ['-c', guard], { encoding: 'utf8', env: { ...process.env, result_dir: directory } });
      assert.equal(result.status, 3, result.stderr);
      assert.match(result.stderr, /no user process was stopped/);
      assert.equal(process.kill(ordinary.pid, 0), true, 'ordinary installation must remain running');
      assert.match(await readFile(join(directory, 'preexisting-omnideck-processes.txt'), 'utf8'), new RegExp(`\\b${ordinary.pid}\\b`));
    } finally {
      ordinary.kill('SIGTERM');
      await new Promise((resolve) => ordinary.exitCode !== null || ordinary.signalCode !== null ? resolve() : ordinary.once('exit', resolve));
    }
  }
  await rm(directory, { recursive: true, force: true });
});

test('Linux update fixture keeps the pinned image and assertions while clearing only its cache', async () => {
  const fixture = linuxGuest.split('current_step="candidate update"')[1].split('run_journey update')[0];
  assert.match(fixture, /podman rm --force "\$\{container_name\}"/);
  assert.match(fixture, /podman rmi "\$\{update_image_ref\}"/);
  assert.match(fixture, /if podman image exists "\$\{update_image_ref\}"; then[\s\S]*?exit 1/);
  assert.match(fixture, /update-fixture-preconditions\.txt/);
  assert.doesNotMatch(fixture, /podman rmi[^\n]*--force|podman volume|podman system prune/);
  const validator = fixture.match(/<<'PY'\n([\s\S]*?)\nPY\n\)"/)[1];
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-update-image-'));
  try {
    const statePath = join(directory, 'setup-state.json');
    const valid = `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`;
    for (const imageRef of [valid, 'ghcr.io/omnideck-dev/omnideck:latest', 'unrelated/image:tag', '--all', `${valid}\n--force`]) {
      await writeFile(statePath, JSON.stringify({ imageRef }));
      const result = spawnSync('python3', ['-', statePath], { input: validator, encoding: 'utf8' });
      assert.equal(result.status === 0, imageRef === valid, result.stderr);
      if (imageRef === valid) assert.equal(result.stdout.trim(), valid);
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test('Windows setup captures diagnostics before completion and preserves failed staging', () => {
  assert.match(windows, /collect_guest_evidence\(\) \{\s+phase_command Diagnostics/);
  assert.match(windows, /setup_attempt % 20 == 0/);
  assert.match(windows, /runonce-setup-current\.png/);
  assert.match(windows, /remote_staged.*keep_vm.*exit_code.*== "0"/);
  const diagnostics = windowsGuest.split('    "Diagnostics" {')[1].split('    "Doctor" {')[0];
  assert.match(diagnostics, /Copy-Item -LiteralPath \$StatePath/);
  assert.match(diagnostics, /Get-Content -LiteralPath \$DesktopLog -Tail 200/);
  assert.match(diagnostics, /desktop-tail\.log/);
  assert.match(diagnostics, /setup-processes\.json/);
  assert.match(diagnostics, /Get-Content -LiteralPath \$InstallLog -Tail 200/);
  assert.match(windowsGuest, /RedirectStandardError.*resume\.stderr\.log/);
  assert.match(windowsGuest, /Join-Path \$WorkDir 'resume\.stderr\.log'/);
  assert.match(diagnostics, /Get-Content -LiteralPath \$LiveLog -Tail 200/);
  assert.match(diagnostics, /-Exclude resume\.stdout\.log,resume\.stderr\.log/);
  assert.match(diagnostics, /Compress-Archive -Force -DestinationPath/);
  assert.doesNotMatch(windows, /Compress-Archive/);
  assert.match(windowsGuest, /Get-SetupFailureCount \| Set-Content -LiteralPath \$ResumeFailureBaseline/);
  assert.match(windowsGuest, /if \(\$FailureCount -gt \$BeforeResume\) \{\s+Write-Host "failed"/);
  assert.match(windows, /setup_status.*== "failed"[\s\S]*?collect_guest_evidence \|\| true\s+return 1/);
});

test('Windows lifecycle qualification rejects WebView2 failed Windows sign-ins', () => {
  assert.match(windowsGuest, /Start-WebViewLogonAudit\s+Invoke-Smoke \$Application/);
  assert.match(windowsGuest, /Invoke-Smoke \$Reinstalled\s+Assert-NoWebViewLogonFailures/);
  assert.match(windowsGuest, /EventID=4625/);
  assert.match(windowsGuest, /EventRecordID > \$StartRecord/);
  assert.match(windowsGuest, /if \(\$Failures\.Count\) \{ throw/);
  assert.match(windowsGuest, /NoMatchingEventsFound/);
  assert.match(windowsGuest, /webview-logon-audit\.json/);
  assert.doesNotMatch(windowsGuest + windowsStartDriver + windows, /WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS|lockoutthreshold|AutofillAiWalletPrivatePasses/);
});

test('Linux browser discovery follows the registered XDG handler, not stale Firefox entries', async () => {
  const root = await mkdtemp(join(tmpdir(), 'omnideck-browser-handler-'));
  try {
    await mkdir(join(root, 'applications'));
    await writeFile(join(root, 'applications', 'org.mozilla.firefox.desktop'), '[Desktop Entry]\n');
    await writeFile(join(root, 'applications', 'firefox_firefox.desktop'), '[Desktop Entry]\n');
    const resolver = linuxGuest.match(/resolve_browser_desktop_entry\(\) \{[\s\S]*?\n\}/)[0];
    for (const handler of ['org.mozilla.firefox.desktop', 'missing.desktop', '../invalid.desktop', '']) {
      const result = spawnSync('bash', ['-c', `
        set -eu
        xdg-mime() { printf '%s' "$TEST_HANDLER"; }
        ${resolver}
        resolve_browser_desktop_entry
        printf '%s' "$browser_desktop_path"
      `], { encoding: 'utf8', env: { ...process.env, XDG_DATA_HOME: root, XDG_DATA_DIRS: root, TEST_HANDLER: handler } });
      if (handler === 'org.mozilla.firefox.desktop') {
        assert.equal(result.status, 0, result.stderr);
        assert.equal(result.stdout, join(root, 'applications', handler));
      } else {
        assert.notEqual(result.status, 0, handler);
      }
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('Linux upgrade tests install exact candidate bytes even at the same version', () => {
  assert.match(linuxGuest, /apt-get install --reinstall -y "\$\{artifact\}"/);
  const installRpm = linuxGuest.match(/install_rpm\(\) \{[\s\S]*?\n\}/)[0];
  for (const installed of [true, false]) {
    const result = spawnSync('bash', ['-c', `
      set -eu
      artifact=/candidate.rpm
      rpm() {
        if [[ "$1" == -qp ]]; then printf 'omnideck-0.1.0-beta.11.x86_64';
        else [[ "$2" == omnideck-0.1.0-beta.11.x86_64 ]]; return ${installed ? 0 : 1}; fi
      }
      dnf_with_lock_retry() { printf '%s\\n' "$@"; }
      ${installRpm}
      install_rpm
    `], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.stdout, `candidate-install\n${installed ? 'reinstall' : 'install'}\n-y\n/candidate.rpm\n`);
  }
});

const polkitAgent = await read('../tests/e2e/polkit_agent.py');
const driver = await read('../tests/e2e/webdriver_client.py');
assert.match(driver, /min\(self\.timeout, 120\)/);
assert.match(driver, /hosted-observations\.json/);
const customAppFixture = await read('../tests/e2e/custom_app_fixture.py');
const hostBoundaryDriver = await read('../tests/e2e/host_boundary_client.py');
const purge = await read('../tests/e2e/purge.sh');
const qualifier = await read('../tests/e2e/qualify-release.sh');
const candidateMatrix = await read('../tests/e2e/candidate-matrix.sh');
assert.match(candidateMatrix, /interrupt_matrix 130 INT/);
assert.match(candidateMatrix, /wait "\$active_lane_pid"/);
const releasePurge = await read('../tests/e2e/purge-release.sh');
const packageSmoke = await read('../tests/e2e/run-package-smoke.sh');
const packageSmokeGuest = await read('../tests/e2e/linux_package_smoke.sh');
const verifyLinuxSmoke = await read('../tests/e2e/verify_linux_smoke.py');
const smokeMatrix = await read('../tests/e2e/smoke-matrix.sh');
const smokeMatrixGuest = await read('../tests/e2e/smoke-matrix-guest.sh');
test('grouped smoke resolves the lab in its child process and leaves the final reset to its lease', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-smoke-child-'));
  try {
    await mkdir(join(directory, 'cells'));
    await writeFile(join(directory, 'lab.sh'), `#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$OMNIDECK_TEST_LAB_CALLS"
case "$1" in
  capabilities) printf '%s\\n' '{"features":["artifact-path","cache-path","lease-cleanup","preflight","profiles"]}' ;;
  profile) echo product-ready-v2 ;;
  reset|start|stop|wait|verify) ;;
  *) exit 9 ;;
esac
`, { mode: 0o755 });
    const environment = { ...process.env, OMNIDECK_VM_LAB_DIR: directory, OMNIDECK_VM_LAB_LEASED: '1', OMNIDECK_TEST_LAB_CALLS: join(directory, 'calls.txt') };
    delete environment.lab_dir;
    const result = spawnSync('bash', [new URL('../tests/e2e/smoke-matrix-guest.sh', import.meta.url).pathname, 'appimage', 'product-ready', directory, join(directory, 'status.tsv')], { env: environment, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const calls = (await readFile(join(directory, 'calls.txt'), 'utf8')).trim().split('\n');
    assert.deepEqual(calls.filter((call) => /^(reset|start|stop|wait|verify) /.test(call)), [
      'reset appimage product-ready-v2', 'start appimage', 'wait appimage', 'verify appimage', 'stop appimage',
    ]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
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
  assert.match(windowsGuest, /-RedirectStandardError \(Join-Path \$Smoke "host\.stderr\.log"\)/);
  assert.match(windowsGuest, /\$Process\.ExitCode/);
  assert.match(windows, /if \[\[ "\$\{exit_code\}" != "0" \]\]; then\n\s+collect_guest_evidence \|\| true/);
  assert.match(windows, /phase_command Driver/);
  assert.match(windows, /if \[\[ "\$\{test_status\}" == "0" \]\]; then\n  stop_driver\n  start_driver preserve/);
  assert.match(driver, /tauri:options/);
  assert.match(driver, /mockup-parity/);
  assert.match(driver, /mockup-html/);
  assert.match(driver, /Uncontracted visible setup copy/);
  assert.match(driver, /EXPECTED_UPDATE_BRIDGE/);
  assert.match(driver, /update-bridge\.json/);
  assert.match(driver, /setup:updating/);
  assert.match(run, /custom_app_fixture\.py/);
  assert.match(run, /verify_linux_smoke\.py/);
  assert.match(packageSmoke, /verify_linux_smoke\.py/);
  assert.match(linuxGuest, /python3 "\$\{work_dir\}\/verify_linux_smoke\.py"/);
  assert.match(packageSmokeGuest, /python3 "\$\{work_dir\}\/verify_linux_smoke\.py"/);
  assert.match(run, /--upgrade-from-artifact/);
  assert.match(run, /upgrade-from\.\$\{bundle\}/);
  assert.match(linuxGuest, /previous release installation/);
  assert.match(linuxGuest, /installed\.AppImage/);
  assert.match(linuxGuest, /appimage\)\n\s+chmod 755 "\$\{artifact\}"/);
  assert.match(linuxGuest, /candidateBinary.*omnideck-desktop/);
  assert.match(linuxGuest, /stateMarkerPreserved/);
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
  assert.match(windows, /upgrade-from-setup\.exe/);
  assert.match(windowsGuest, /Previous NSIS install failed/);
  assert.match(windowsGuest, /legacy omnideck\.exe remained/);
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
  assert.match(linuxGuest, /omnideck-e2e-firefox\.desktop/);
  assert.match(linuxGuest, /MOZ_ENABLE_WAYLAND=1/);
  assert.match(linuxGuest, /xdg-mime query default x-scheme-handler\/https/);
  assert.match(run, /update-notifier\.desktop/);
  assert.match(run, /pkill -u tester -TERM -x update-manager/);
  assert.match(windowsGuest, /HostBoundaryDownload/);
  assert.match(windowsGuest, /HostBoundaryArtifactDownload/);
  assert.match(windowsGuest, /SeedUpdateFixture/);
  assert.match(windows, /-FixtureName \\\"\$\{fixture_name\}\\\"/);
  assert.match(hostBoundaryDriver, /send_keys/);
  assert.match(hostBoundaryDriver, /Export navigated the hosted application/);
  assert.match(hostBoundaryDriver, /Download complete/);
  assert.match(hostBoundaryDriver, /artifact_download/);
  assert.match(hostBoundaryDriver, /"vm-hardware-keyboard"/);
  assert.match(hostBoundaryDriver, /nativeWebviewZoomApplied/);
  assert.match(hostBoundaryDriver, /cssZoomApplied/);
  assert.match(hostBoundaryDriver, /assert_zoom_layout/);
  assert.match(hostBoundaryDriver, /keyboardZoomOut/);
  assert.match(hostBoundaryDriver, /anchorError/);
  assert.match(hostBoundaryDriver, /__omnideckZoomMenuOpeningAnchor/);
  assert.match(hostBoundaryDriver, /viewportWidthError/);
  assert.match(hostBoundaryDriver, /cssZoom: root\.style\.zoom/);
  assert.match(hostBoundaryDriver, /zoom-input-\{external_input_count:03d\}-\{action\}/);
  assert.match(hostBoundaryDriver, /native-input-signal-dir/);
  assert.match(linuxGuest, /--native-input-signal-dir/);
  assert.match(run, /zoom-input-\[0-9\]\+-\(in\|out\|reset\)/);
  assert.match(run, /clean GNOME session can leave both a system notification and Overview/);
  assert.match(run, /for focus_escape in 1 2/);
  assert.match(run, /send-keys "\$\{vm\}" "\$\{zoom_key\}"/);
  assert.match(run, /ctrl-equal/);
  assert.match(run, /ctrl-minus/);
  assert.match(run, /ctrl-0/);
  assert.match(windows, /--native-input-signal-dir/);
  assert.match(windows, /zoom-input-\[0-9\]\+-\(in\|out\|reset\)/);
  assert.match(windows, /send-keys windows "\$\{key\}"/);
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

test('the GNU Windows lab builder disables unintended DLL auto-exports', () => {
  assert.match(windowsBuilderDockerfile, /link-arg=-Wl,--exclude-all-symbols/);
});

test('Desktop VM evidence and destructive cleanup remain run-scoped', () => {
  assert.match(linuxGuest, /journalctl --since "\$\{started_at\}" --no-pager/);
  assert.match(linuxGuest, /coredumpctl --since "\$\{started_at\}" --no-pager info/);
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
  assert.match(qualifier, /--upgrade-from previous\|none\|TAG/);
  assert.match(qualifier, /resolve_previous_release/);
  assert.match(qualifier, /upgrade-release-contract\.json/);
  assert.match(candidateMatrix, /upgrade_from=.*latest/);
  assert.match(candidateMatrix, /upgrade-release-contract\.json/);
  assert.match(candidateMatrix, /--upgrade-from-artifact/);
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
  assert.match(verifyLinuxSmoke, /\["--version", "--json runtime status"\]/);
  assert.match(smokeMatrix, /appimage:appimage\|deb:deb\|rpm:rpm\|atomic:appimage/);
  assert.match(smokeMatrix, /for package_kind in appimage deb rpm flatpak/);
  assert.match(smokeMatrix, /finish_incomplete_matrix/);
  assert.match(smokeMatrix, /evidence_status=canceled/);
  assert.match(smokeMatrix, /lease "\$\{vm\}" desktop-smoke-matrix/);
  assert.match(smokeMatrixGuest, /OMNIDECK_DESKTOP_VM_SMOKE_REUSE_GUEST=1/);
  assert.match(smokeMatrixGuest, /Preparing %s once/);
});

test('native macOS E2E leases the physical ARM host and drives the production app through Accessibility', () => {
  assert.match(macos, /artifact-path desktop macos-e2e/);
  assert.match(macos, /lease "\$target" desktop-e2e/);
  assert.match(macos, /--cleanup-baseline runtime-ready/);
  assert.match(macos, /evidence-init/);
  assert.match(macos, /evidence-finish/);
  assert.match(macos, /artifactSha256=/);
  assert.match(macosGuest, /Omnideck Lab\.app/);
  assert.match(macosGuest, /Omnideck Lab Driver\.app/);
  assert.match(macosGuest, /OMNIDECK_DESKTOP_TEST_NAMESPACE/);
  assert.match(macosGuest, /release-test-macos/);
  assert.match(macosGuest, /no user process was stopped/);
  assert.doesNotMatch(macosGuest, /pkill -f '\/omnideck(?:-desktop)?\$'/);
  assert.match(macos, /--upgrade-from-artifact/);
  assert.match(macosGuest, /previous DMG installation/);
  assert.match(macosGuest, /stateMarkerPreserved/);
  assert.match(macosGuest, /Set up omnideck/);
  assert.match(macosGuest, /Open omnideck/);
  assert.match(macosGuest, /Try again/);
  assert.match(macosGuest, /Port \$old_port is already in use/);
  assert.match(macosGuest, /Custom App native WebView action/);
  assert.match(macosGuest, /Custom App restart persistence/);
  assert.match(macosGuest, /external browser and internal navigation/);
  assert.match(macosGuest, /External browser link in new window/);
  assert.match(macosGuest, /native host download/);
  assert.match(macosGuest, /click-in "\$application" "Export/);
  assert.match(macosGuest, /native host upload/);
  assert.match(macosGuest, /native artifact download and toast/);
  assert.match(macosGuest, /native update bridge visible contract/);
  assert.match(macosGuest, /OMNIDECK_DESKTOP_UPDATE_FIXTURE/);
  assert.match(macosGuest, /omnideck-lab-input\.dylib/);
  assert.match(macosGuest, /mouse_click "\$fixture_filename"/);
  assert.match(macosGuest, /mouse_click "\$artifact_filename"/);
  assert.match(macosGuest, /DMG removal preserves user and runtime data/);
  assert.match(macosGuest, /DMG reinstall and packaged sidecar smoke/);
  assert.match(macosGuest, /width >= 640 and height >= 400/);
  assert.match(macosGuest, /grep -q '\^screenshots='/);
  assert.doesNotMatch(macosGuest, /native zoom shortcut/);
  assert.doesNotMatch(macos, /--only zoom/);
  assert.match(macosGuest, /tests="17" failures="0"/);
  assert.match(macosGuest, /soft_failures/);
  assert.match(macosGuest, /complete journey/);
  assert.match(macosGuest, /container-inspect\.json/);
  assert.match(macosGuest, /volume-inspect\.json/);
  assert.doesNotMatch(macos, /tauri-driver|webdriver_client/);
  assert.doesNotMatch(macosGuest, /tauri-driver|webdriver_client/);
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
  assert.equal(golden.linux.debianRecommendedBaseline, 'desktop-e2e-v4');
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
  assert.match(run, /--cleanup-baseline "?\$baseline"?/);
  assert.match(windows, /--cleanup-baseline "?\$baseline"?/);
});

test('current Linux guests install only the input dependencies their lane uses', () => {
  assert.match(linuxGuest, /apt-get install -y -qq webkit2gtk-driver/);
  assert.doesNotMatch(linuxGuest, /xdotool/);
  assert.match(linuxGuest, /dnf_with_lock_retry input-dependencies install -y webkitgtk6\.0/);
  assert.match(linuxGuest, /Failed to obtain rpm transaction lock/);
  assert.match(linuxGuest, /attempt < 31/);
  assert.match(JSON.stringify(golden), /VM-controller hardware keyboard injection/);
});

test('host-boundary journeys retry only transient WebDriver disconnects', () => {
  assert.match(linuxGuest, /for attempt in 1 2 3/);
  assert.match(
    linuxGuest,
    /WebDriverError:\.\*\(Remote end closed\|Connection reset\|Connection refused\)/,
  );
  assert.match(linuxGuest, /transient-failure-attempt-/);
});

test('Windows WebView forwarding uses a free host port and observes tunnel death before readiness', () => {
  assert.match(windows, /listener\.bind\(\(\"127\.0\.0\.1\", 0\)\)/);
  const tunnelLoop = windows.match(/for attempt in \$\(seq 1 480\); do([\s\S]*?)done/);
  assert.ok(tunnelLoop);
  assert.ok(
    tunnelLoop[1].indexOf('kill -0 "${driver_ssh_pid}"') <
      tunnelLoop[1].indexOf('curl --silent --fail'),
  );
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
  assert.match(windowsGuest, /version = "0\.5\.3"/);
});

test('desktop cleanup preserves evidence and delegates final reset to its lease', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'omnideck-cleanup-owner-'));
  const actions = join(directory, 'actions');
  await writeFile(join(directory, 'lab.sh'), '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$AUDIT_ACTIONS"\nif [[ "$1" == stop && "$AUDIT_STOP_FAIL" == 1 ]]; then exit 1; fi\n', { mode: 0o755 });
  try {
    for (const [name, source] of [['linux', run], ['windows', windows]]) {
      const cleanup = `cleanup() {${source.split('cleanup() {')[1].split('\ntrap cleanup EXIT')[0]}`;
      for (const [exitCode, complete, keep, stopFails, expected] of [[0, 1, 0, 0, 0], [9, 1, 0, 0, 9], [0, 0, 0, 0, 1], [0, 1, 1, 0, 0], [0, 1, 0, 1, 1]]) {
        await writeFile(actions, '');
        const result = spawnSync('bash', ['-c', `${cleanup}\ntrap cleanup EXIT\nexit "$AUDIT_EXIT"`], {
          encoding: 'utf8',
          env: { ...process.env, lab_dir: directory, vm: 'appimage', output_dir: directory, remote_staged: '0', vm_started: '1', driver_ssh_pid: '', driver_task_name: 'owned-test', trust_task_name: 'owned-trust', qualification_complete: String(complete), keep_vm: String(keep), AUDIT_ACTIONS: actions, AUDIT_EXIT: String(exitCode), AUDIT_STOP_FAIL: String(stopFails) },
        });
        const log = (await readFile(actions, 'utf8')).trim().split('\n');
        assert.equal(result.status, expected, `${name}: ${result.stderr}`);
        assert.equal(log.filter((line) => line.startsWith('stop ')).length, 1);
        assert.equal(log.filter((line) => line.startsWith('reset ')).length, 0, 'lease must receive the tested guest state for failure retention and final reset');
        assert.ok(log.includes(`evidence-finish ${directory} ${expected === 0 ? 'passed' : 'failed'}`));
        if (keep) assert.match(result.stdout, /kept stopped for debugging/);
      }
    }
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
