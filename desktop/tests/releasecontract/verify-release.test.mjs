import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { verifyReleaseDirectory } from './verify-release.mjs';

const version = 'v1.2.3-alpha.4';
const bareVersion = version.slice(1);
const artifacts = [
  ['nsis', `omnideck_${bareVersion}_x64-setup.exe`, 'x64'],
  ['nsis', `omnideck_${bareVersion}_arm64-setup.exe`, 'arm64'],
  ['dmg', `omnideck_${bareVersion}_x64.dmg`, 'x64'],
  ['dmg', `omnideck_${bareVersion}_aarch64.dmg`, 'arm64'],
  ['appimage', `omnideck_${bareVersion}_amd64.AppImage`, 'x64'],
  ['appimage', `omnideck_${bareVersion}_aarch64.AppImage`, 'arm64'],
  ['deb', `omnideck_${bareVersion}_amd64.deb`, 'x64'],
  ['deb', `omnideck_${bareVersion}_arm64.deb`, 'arm64'],
  ['rpm', `omnideck-${bareVersion}-1.x86_64.rpm`, 'x64'],
  ['rpm', `omnideck-${bareVersion}-1.aarch64.rpm`, 'arm64'],
];

function fixture(format, architecture) {
  const contents = Buffer.alloc(2048);
  if (format === 'nsis') contents.write('MZ', 0, 'ascii');
  if (format === 'dmg') contents.write('koly', contents.length - 512, 'ascii');
  if (format === 'appimage') {
    contents.set([0x7f, 0x45, 0x4c, 0x46], 0);
    contents[5] = 1;
    contents.writeUInt16LE(architecture === 'x64' ? 62 : 183, 18);
  }
  if (format === 'deb') contents.write('!<arch>\n', 0, 'ascii');
  if (format === 'rpm') contents.set([0xed, 0xab, 0xee, 0xdb], 0);
  return contents;
}

async function makeRelease() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'omnideck-release-contract-'));
  for (const [format, name, architecture] of artifacts) {
    const contents = fixture(format, architecture);
    const digest = createHash('sha256').update(contents).digest('hex');
    await writeFile(path.join(root, name), contents);
    await writeFile(path.join(root, `${name}.sha256`), `${digest}  ${name}\n`);
  }
  return root;
}

test('accepts the complete desktop package matrix with matching checksums', async (t) => {
  const root = await makeRelease();
  t.after(() => rm(root, { recursive: true, force: true }));
  const report = await verifyReleaseDirectory({ directory: root, version });
  assert.equal(report.result, 'pass');
  assert.equal(report.artifactCount, 10);
  assert.deepEqual(new Set(report.artifacts.map(({ platform }) => platform)), new Set(['windows', 'macos', 'linux']));
});

test('rejects a package whose checksum does not match', async (t) => {
  const root = await makeRelease();
  t.after(() => rm(root, { recursive: true, force: true }));
  const name = `omnideck_${bareVersion}_x64-setup.exe`;
  await writeFile(path.join(root, `${name}.sha256`), `${'0'.repeat(64)}  ${name}\n`);
  await assert.rejects(
    verifyReleaseDirectory({ directory: root, version }),
    /checksum mismatch/,
  );
});

test('rejects an AppImage with the wrong executable architecture', async (t) => {
  const root = await makeRelease();
  t.after(() => rm(root, { recursive: true, force: true }));
  const name = `omnideck_${bareVersion}_aarch64.AppImage`;
  const contents = fixture('appimage', 'x64');
  const digest = createHash('sha256').update(contents).digest('hex');
  await writeFile(path.join(root, name), contents);
  await writeFile(path.join(root, `${name}.sha256`), `${digest}  ${name}\n`);
  await assert.rejects(
    verifyReleaseDirectory({ directory: root, version }),
    /wrong ELF architecture/,
  );
});
