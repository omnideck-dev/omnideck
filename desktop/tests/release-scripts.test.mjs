import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const linux = await read('../scripts/release-test/linux.sh');
const macos = await read('../scripts/release-test/macos.sh');
const windows = await read('../scripts/release-test/windows.ps1');
const resetWindows = await read('../scripts/release-test/reset-host.ps1');
const common = await read('../scripts/release-test/_common.sh');
const desktopWorkflow = await read('../../.github/workflows/desktop.yml');
const hardwareWorkflow = await read('../../.github/workflows/desktop-hardware.yml');
const publishedWorkflow = await read('../../.github/workflows/desktop-release-contract.yml');

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
