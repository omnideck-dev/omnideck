import assert from 'node:assert/strict';
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const signingTest = (name, run) => test(name, {
  skip: process.platform === 'win32' && 'POSIX signing gate fixtures',
}, run);

// Exercise the release gate with real codesign-output shapes. Apple tools are
// mocked here; live signing/notarization is a separate native qualification.
function verify(overrides = {}) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'omnideck-signing-test-'));
  try {
    const scripts = path.join(root, 'desktop/scripts');
    const tools = path.join(root, 'tools');
    const assets = path.join(root, 'desktop/src-tauri/assets');
    const dmg = path.join(root, 'desktop/src-tauri/target/aarch64-apple-darwin/release/bundle/dmg');
    for (const directory of [scripts, tools, assets, dmg]) mkdirSync(directory, { recursive: true });
    copyFileSync(new URL('../scripts/verify-macos-bundle.sh', import.meta.url), path.join(scripts, 'verify.sh'));
    writeFileSync(path.join(assets, 'dmg-background.png'), 'background');
    writeFileSync(path.join(dmg, 'omnideck.dmg'), 'disk image fixture');
    const commands = {
      uname: 'echo Darwin',
      hdiutil: `
if [[ "$1" == attach ]]; then
  while [[ "$1" != -mountpoint ]]; do shift; done
  mount="$2"
  mkdir -p "$mount/omnideck.app/Contents/MacOS" "$mount/.background"
  ln -s /Applications "$mount/Applications"
  touch "$mount/.DS_Store"
  [[ "\${MISSING_CLI:-}" == true ]] || touch "$mount/omnideck.app/Contents/MacOS/omnideck-cli"
  printf background > "$mount/.background/dmg-background.png"
else
  rm -rf -- "$2"/* "$2"/.background "$2"/.DS_Store
fi`,
      codesign: `
[[ "$1" == --display ]] || exit 0
subject="\${!#}"
team=2FL6BUG8Q4
[[ "$subject" != */omnideck-cli ]] || team="\${CLI_TEAM:-2FL6BUG8Q4}"
printf 'Authority=Developer ID Application: Test\\nTeamIdentifier=%s\\nTimestamp=Oct 8 2026\\n' "$team"
if [[ "$subject" != *.dmg ]]; then
  printf 'CodeDirectory v=20500 size=281 flags=0x10000(runtime) hashes=3+2 location=embedded\\n'
fi`,
      xcrun: '[[ "${TICKET_INVALID:-}" != true ]]',
      spctl: '[[ "${GATEKEEPER_REJECTS:-}" != true ]]',
    };
    for (const [command, body] of Object.entries(commands)) {
      writeFileSync(path.join(tools, command), `#!/bin/bash\nset -e\n${body}\n`, { mode: 0o755 });
    }
    return spawnSync('bash', [path.join(scripts, 'verify.sh'), 'aarch64-apple-darwin', '--require-developer-id', '2FL6BUG8Q4'], {
      env: { ...process.env, ...overrides, PATH: `${tools}:${process.env.PATH}` }, encoding: 'utf8',
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

signingTest('macOS release gate accepts CodeDirectory runtime flags and the signed bundled CLI', () => {
  const result = verify();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Assessing disk image with Gatekeeper/);
});

signingTest('macOS release gate rejects a bundled CLI from a different Apple team', () => {
  const result = verify({ CLI_TEAM: 'WRONGTEAM1' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /bundled CLI is missing the expected Developer ID/);
});

signingTest('macOS release gate rejects a missing bundled CLI', () => {
  const result = verify({ MISSING_CLI: 'true' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Missing bundled CLI/);
});

signingTest('macOS release gate fails closed on an invalid stapled ticket', () => {
  assert.notEqual(verify({ TICKET_INVALID: 'true' }).status, 0);
});

signingTest('macOS release gate fails closed when Gatekeeper rejects the application', () => {
  assert.notEqual(verify({ GATEKEEPER_REJECTS: 'true' }).status, 0);
});
