import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const linux = await read('../scripts/release-test/linux.sh');
const macos = await read('../scripts/release-test/macos.sh');
const windows = await read('../scripts/release-test/windows.ps1');
const resetWindows = await read('../scripts/release-test/reset-host.ps1');
const common = await read('../scripts/release-test/_common.sh');
const macosBundleVerifier = await read('../scripts/verify-macos-bundle.sh');
const buildWithRetry = await read('../scripts/build-with-retry.mjs');
const desktopWorkflow = await read('../../.github/workflows/desktop.yml');
const hardwareWorkflow = await read('../../.github/workflows/desktop-hardware.yml');
const publishedWorkflow = await read('../../.github/workflows/desktop-release-contract.yml');
const tauriConfig = JSON.parse(await read('../src-tauri/tauri.conf.json'));
const dmgBackgroundSource = await read('../src-tauri/assets/dmg-background.svg');
const dmgBackground = await readFile(new URL('../src-tauri/assets/dmg-background.png', import.meta.url));

test('published release helpers verify checksums and provenance before launch', () => {
  for (const script of [linux, macos]) {
    assert.match(script, /sha(?:256sum|sum -a 256) --check/);
    assert.match(script, /gh attestation verify/);
    assert.match(script, /tests\/hardware\/run\.sh/);
  }
  assert.match(windows, /Get-FileHash/);
  assert.match(windows, /gh attestation verify/);
  assert.match(windows, /tests\\hardware\\run\.ps1/);
});

test('release helpers select both published native architectures', () => {
  assert.match(linux, /x86_64\) artifact_arch="amd64"/);
  assert.match(linux, /aarch64\|arm64\) artifact_arch="aarch64"/);
  assert.match(macos, /arm64\) artifact_arch="aarch64"/);
  assert.match(macos, /x86_64\) artifact_arch="x64"/);
  assert.match(windows, /ValidateSet\("Auto", "x64", "arm64"\)/);
});

test('destructive reset and isolated Unix scenarios retain explicit safety boundaries', () => {
  assert.match(resetWindows, /\[switch\]\$Inventory/);
  assert.match(resetWindows, /\[switch\]\$DryRun/);
  assert.match(resetWindows, /Read-Host/);
  assert.match(resetWindows, /Administrator/);
  assert.match(common, /Refusing to modify a profile outside/);
  assert.match(common, /Type \$\{TEST_NAMESPACE\} to continue/);
  assert.match(common, /preserved/);
});

test('hosted CI, public artifact validation, and native hardware remain distinct', () => {
  assert.match(desktopWorkflow, /artifact_contract:/);
  assert.match(desktopWorkflow, /environment: release/);
  assert.match(publishedWorkflow, /workflow_dispatch:/);
  assert.match(publishedWorkflow, /gh attestation verify/);
  assert.match(hardwareWorkflow, /workflow_dispatch:/);
  assert.match(hardwareWorkflow, /runs-on: \[self-hosted, omnideck-desktop/);
  assert.doesNotMatch(hardwareWorkflow, /pull_request:/);
});

test('native package builds retry transient Tauri helper downloads', () => {
  assert.match(desktopWorkflow, /node scripts\/build-with-retry\.mjs \$\{\{ matrix\.command \}\}/);
  assert.match(buildWithRetry, /const maxAttempts = 3/);
  assert.match(buildWithRetry, /attempt \* 5_000/);
  assert.match(buildWithRetry, /spawnSync\(`pnpm run \$\{packageScript\}`/);
  assert.match(buildWithRetry, /targetByPackageScript/);
  assert.match(buildWithRetry, /rmSync\(bundleDirectory, \{ recursive: true, force: true \}\)/);
});

test('macOS release packages contain a strict bundle-level signature', () => {
  assert.match(desktopWorkflow, /Verify the packaged macOS app signature/);
  assert.match(desktopWorkflow, /if: runner\.os == 'macOS'/);
  assert.match(desktopWorkflow, /verify-macos-bundle\.sh \$\{\{ matrix\.target \}\}/);
  assert.match(macosBundleVerifier, /codesign --verify --deep --strict --verbose=4/);
  assert.match(macosBundleVerifier, /hdiutil attach -readonly -nobrowse/);
  assert.match(macosBundleVerifier, /Tauri removed the intermediate app/);
  assert.match(macosBundleVerifier, /mounted_apps=/);
  assert.match(macosBundleVerifier, /Info\.plist=not bound/);
  assert.match(macosBundleVerifier, /Sealed Resources=none/);
  assert.match(macosBundleVerifier, /linker-signed/);
});

test('macOS DMG presents and verifies the conventional Applications drop target', () => {
  assert.deepEqual(tauriConfig.bundle.macOS.dmg, {
    background: 'assets/dmg-background.png',
    windowSize: { width: 716, height: 458 },
    appPosition: { x: 208, y: 204 },
    applicationFolderPosition: { x: 508, y: 204 },
  });
  assert.match(macosBundleVerifier, /does not contain the Applications drag-and-drop target/);
  assert.match(macosBundleVerifier, /readlink/);
  assert.match(macosBundleVerifier, /\/Applications/);
  assert.match(macosBundleVerifier, /does not contain Finder layout metadata/);
  assert.match(macosBundleVerifier, /\.background\/dmg-background\.png/);
  assert.match(macosBundleVerifier, /cmp -s/);
  assert.equal(dmgBackground.readUInt32BE(16), 716);
  assert.equal(dmgBackground.readUInt32BE(20), 429);
  assert.match(dmgBackgroundSource, /Drag omnideck into Applications/);
  assert.match(dmgBackgroundSource, /Eject “omnideck” in Finder/);
  assert.match(dmgBackgroundSource, /Move the downloaded DMG to Trash/);
  assert.match(desktopWorkflow, /TAURI_BUNDLER_DMG_IGNORE_CI: "true"/);
});
