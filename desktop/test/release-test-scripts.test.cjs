const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const releaseTestRoot = path.join(__dirname, '..', 'scripts', 'release-test');

test('Windows release tests use the normal omnideck runtime instead of an isolated WSL machine', () => {
  const source = fs.readFileSync(path.join(releaseTestRoot, 'windows.ps1'), 'utf8');

  assert.match(source, /\$MachineName = "omnideck-runtime"/);
  assert.match(source, /\$ProfileRoot = .*\$env:APPDATA "omnideck"/);
  assert.doesNotMatch(source, /OMNIDECK_DESKTOP_TEST_NAMESPACE/);
  assert.doesNotMatch(source, /TestProfile|TestNamespace|odrt-release-test/);
});

test('Windows host reset removes WSL, Podman, and both omnideck clients', () => {
  const source = fs.readFileSync(path.join(releaseTestRoot, 'reset-host.ps1'), 'utf8');

  assert.match(source, /wsl\.exe --unregister/);
  assert.match(source, /wsl\.exe --uninstall/);
  assert.match(source, /"VirtualMachinePlatform"/);
  assert.match(source, /"Microsoft-Windows-Subsystem-Linux"/);
  assert.match(source, /"omnideck-cli"/);
  assert.match(source, /"Programs\\omnideck"/);
  assert.match(source, /"Programs\\Podman"/);
});

test('Windows host reset can remove Podman and omnideck while preserving WSL', () => {
  const source = fs.readFileSync(path.join(releaseTestRoot, 'reset-host.ps1'), 'utf8');

  assert.match(source, /\[switch\]\$PreserveWsl/);
  assert.match(source, /if \(\$PreserveWsl\) \{[\s\S]*?podman\.exe machine rm|if \(\$PreserveWsl\) \{[\s\S]*?machine rm --force/);
  assert.match(source, /if \(-not \$PreserveWsl\) \{[\s\S]*?wsl\.exe --unregister/);
  assert.match(source, /if \(-not \$PreserveWsl[^)]*\)[\s\S]*?wsl\.exe --uninstall/);
  assert.match(source, /if \(-not \$PreserveWsl\) \{[\s\S]*?\/disable-feature/);
});
