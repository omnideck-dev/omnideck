import assert from 'node:assert/strict';
import { chmod, readdir, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const binaryRoot = path.resolve(scriptRoot, '../src-tauri/binaries');
const manifest = JSON.parse(await readFile(path.join(binaryRoot, 'vendor-manifest.json'), 'utf8'));

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function filename(targetTriple) {
  const extension = targetTriple.includes('windows') ? '.exe' : '';
  return `omnideck-cli-${targetTriple}${extension}`;
}

function verifyExecutableHeader(targetTriple, contents) {
  if (targetTriple.includes('windows')) {
    assert.equal(contents.readUInt16LE(0), 0x5a4d, `${targetTriple} is not PE`);
    const peOffset = contents.readUInt32LE(0x3c);
    assert.equal(contents.readUInt32LE(peOffset), 0x00004550, `${targetTriple} has no PE signature`);
    const expected = targetTriple.startsWith('x86_64') ? 0x8664 : 0xaa64;
    assert.equal(contents.readUInt16LE(peOffset + 4), expected, `${targetTriple} has the wrong PE machine`);
    return;
  }
  if (targetTriple.includes('linux')) {
    assert.deepEqual([...contents.subarray(0, 4)], [0x7f, 0x45, 0x4c, 0x46], `${targetTriple} is not ELF`);
    assert.equal(contents[5], 1, `${targetTriple} ELF is not little endian`);
    const expected = targetTriple.startsWith('x86_64') ? 62 : 183;
    assert.equal(contents.readUInt16LE(18), expected, `${targetTriple} has the wrong ELF machine`);
    return;
  }
  assert.equal(contents.readUInt32LE(0), 0xfeedfacf, `${targetTriple} is not 64-bit Mach-O`);
  const expected = targetTriple.startsWith('x86_64') ? 0x01000007 : 0x0100000c;
  assert.equal(contents.readUInt32LE(4), expected, `${targetTriple} has the wrong Mach-O CPU type`);
}

assert.equal(manifest.schemaVersion, 1);
assert.equal(manifest.targets.length, 6);
assert.equal(new Set(manifest.targets.map(({ targetTriple }) => targetTriple)).size, 6);

const knownTargets = new Map(manifest.targets.map((target) => [target.targetTriple, target]));
const requestedTargets = process.argv.slice(2).filter((argument) => argument !== '--');
const selectedTargets = requestedTargets.length === 0
  ? manifest.targets
  : requestedTargets.map((targetTriple) => {
      assert(knownTargets.has(targetTriple), `unsupported CLI target: ${targetTriple}`);
      return knownTargets.get(targetTriple);
    });

for (const target of selectedTargets) {
  const executable = path.join(binaryRoot, filename(target.targetTriple));
  const contents = await readFile(executable);
  assert.equal(sha256(contents), target.binarySha256, `${target.targetTriple} binary checksum mismatch`);
  verifyExecutableHeader(target.targetTriple, contents);

  const sbom = await readFile(path.join(binaryRoot, 'sbom', target.sbom));
  assert.equal(sha256(sbom), target.sbomSha256, `${target.targetTriple} SBOM checksum mismatch`);
}

const expectedFiles = new Set(manifest.targets.map(({ targetTriple }) => filename(targetTriple)));
const actualFiles = (await readdir(binaryRoot)).filter((entry) => entry.startsWith('omnideck-cli-'));
for (const entry of actualFiles) {
  assert(expectedFiles.has(entry), `unexpected sidecar is not pinned by the manifest: ${entry}`);
}
for (const target of selectedTargets) {
  assert(actualFiles.includes(filename(target.targetTriple)), `${target.targetTriple} sidecar is missing`);
}

const hostArch = process.arch === 'x64' ? 'x86_64' : process.arch === 'arm64' ? 'aarch64' : null;
const hostPlatform = { win32: 'pc-windows-msvc', darwin: 'apple-darwin', linux: 'unknown-linux-gnu' }[process.platform];
const hostTarget = hostArch && hostPlatform ? `${hostArch}-${hostPlatform}` : null;
if (hostTarget && selectedTargets.some(({ targetTriple }) => targetTriple === hostTarget)) {
  const executable = path.join(binaryRoot, filename(hostTarget));
  if (process.platform !== 'win32') await chmod(executable, 0o755);
  const result = spawnSync(executable, ['--version'], { encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr || 'native sidecar --version failed');
  assert.equal(
    result.stdout.trim(),
    `omnideck version ${manifest.version} (${manifest.commit}) built ${manifest.builtAt}`,
    'native sidecar version does not match the vendor manifest',
  );
}

process.stdout.write(
  `Verified ${manifest.version} (${manifest.commit}) for ${selectedTargets.length} desktop target(s).\n`,
);
