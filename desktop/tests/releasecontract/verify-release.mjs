import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const VERSION_PATTERN = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$/;
const PACKAGE_PATTERN = /\.(?:AppImage|deb|dmg|exe|rpm)$/i;

function expectedArtifacts(version) {
  const bareVersion = version.slice(1);
  return [
    { name: `omnideck_${bareVersion}_x64-setup.exe`, platform: 'windows', architecture: 'x64', format: 'nsis' },
    { name: `omnideck_${bareVersion}_arm64-setup.exe`, platform: 'windows', architecture: 'arm64', format: 'nsis' },
    { name: `omnideck_${bareVersion}_x64.dmg`, platform: 'macos', architecture: 'x64', format: 'dmg' },
    { name: `omnideck_${bareVersion}_aarch64.dmg`, platform: 'macos', architecture: 'arm64', format: 'dmg' },
    { name: `omnideck_${bareVersion}_amd64.AppImage`, platform: 'linux', architecture: 'x64', format: 'appimage' },
    { name: `omnideck_${bareVersion}_aarch64.AppImage`, platform: 'linux', architecture: 'arm64', format: 'appimage' },
    { name: `omnideck_${bareVersion}_amd64.deb`, platform: 'linux', architecture: 'x64', format: 'deb' },
    { name: `omnideck_${bareVersion}_arm64.deb`, platform: 'linux', architecture: 'arm64', format: 'deb' },
    { name: `omnideck-${bareVersion}-1.x86_64.rpm`, platform: 'linux', architecture: 'x64', format: 'rpm' },
    { name: `omnideck-${bareVersion}-1.aarch64.rpm`, platform: 'linux', architecture: 'arm64', format: 'rpm' },
  ];
}

async function filesBelow(root) {
  const files = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const candidate = path.join(directory, entry.name);
      if (entry.isDirectory()) await visit(candidate);
      else files.push(candidate);
    }
  }
  await visit(root);
  return files;
}

function sha256(contents) {
  return createHash('sha256').update(contents).digest('hex');
}

function verifyMagic(descriptor, contents) {
  assert(contents.length >= 1024, `${descriptor.name} is unexpectedly small`);
  if (descriptor.format === 'nsis') {
    assert.equal(contents.subarray(0, 2).toString('ascii'), 'MZ', `${descriptor.name} is not a PE executable`);
    return;
  }
  if (descriptor.format === 'dmg') {
    assert.equal(contents.subarray(-512, -508).toString('ascii'), 'koly', `${descriptor.name} has no UDIF trailer`);
    return;
  }
  if (descriptor.format === 'appimage') {
    assert.deepEqual([...contents.subarray(0, 4)], [0x7f, 0x45, 0x4c, 0x46], `${descriptor.name} is not ELF`);
    assert.equal(contents[5], 1, `${descriptor.name} is not a little-endian ELF image`);
    const expectedMachine = descriptor.architecture === 'x64' ? 62 : 183;
    assert.equal(contents.readUInt16LE(18), expectedMachine, `${descriptor.name} contains the wrong ELF architecture`);
    return;
  }
  if (descriptor.format === 'deb') {
    assert.equal(contents.subarray(0, 8).toString('ascii'), '!<arch>\n', `${descriptor.name} is not a Debian archive`);
    return;
  }
  assert.deepEqual([...contents.subarray(0, 4)], [0xed, 0xab, 0xee, 0xdb], `${descriptor.name} is not an RPM`);
}

export async function verifyReleaseDirectory({ directory, version }) {
  assert.match(version, VERSION_PATTERN, 'version must be a SemVer tag such as v0.1.0-alpha.8');
  const root = path.resolve(directory);
  const files = await filesBelow(root);
  const byName = new Map();
  for (const file of files) {
    const name = path.basename(file);
    assert(!byName.has(name), `duplicate release filename: ${name}`);
    byName.set(name, file);
  }

  const expected = expectedArtifacts(version);
  const expectedNames = new Set(expected.map(({ name }) => name));
  const publishedPackages = [...byName.keys()].filter((name) => PACKAGE_PATTERN.test(name));
  assert.deepEqual(
    publishedPackages.sort(),
    [...expectedNames].sort(),
    'published desktop package matrix does not match the supported ten artifacts',
  );

  const artifacts = [];
  for (const descriptor of expected) {
    const artifactPath = byName.get(descriptor.name);
    const checksumName = `${descriptor.name}.sha256`;
    const checksumPath = byName.get(checksumName);
    assert(artifactPath, `missing release artifact: ${descriptor.name}`);
    assert(checksumPath, `missing checksum: ${checksumName}`);

    const contents = await readFile(artifactPath);
    verifyMagic(descriptor, contents);
    const digest = sha256(contents);
    const checksum = (await readFile(checksumPath, 'utf8')).trim();
    const match = checksum.match(/^([a-fA-F0-9]{64})\s{2}([^\r\n]+)$/);
    assert(match, `${checksumName} must contain one sha256sum-compatible line`);
    assert.equal(match[2], descriptor.name, `${checksumName} names the wrong artifact`);
    assert.equal(match[1].toLowerCase(), digest, `${descriptor.name} checksum mismatch`);

    artifacts.push({
      ...descriptor,
      sha256: digest,
      size: contents.length,
    });
  }

  return {
    schemaVersion: 1,
    release: version,
    result: 'pass',
    artifactCount: artifacts.length,
    artifacts,
  };
}

function parseArguments(arguments_) {
  const result = {};
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (!['--directory', '--version', '--report'].includes(argument)) {
      throw new Error(`unknown argument: ${argument}`);
    }
    result[argument.slice(2)] = arguments_[index + 1];
    index += 1;
  }
  assert(result.directory, '--directory is required');
  assert(result.version, '--version is required');
  return result;
}

export async function main(arguments_ = process.argv.slice(2)) {
  const options = parseArguments(arguments_);
  const report = await verifyReleaseDirectory(options);
  if (options.report) {
    const reportPath = path.resolve(options.report);
    await mkdir(path.dirname(reportPath), { recursive: true });
    await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`Verified ${report.artifactCount} desktop packages for ${report.release}.\n`);
  return report;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main();
}
