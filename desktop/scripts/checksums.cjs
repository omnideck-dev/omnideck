const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const RELEASE_EXTENSIONS = new Set(['.AppImage', '.deb', '.dmg', '.exe', '.rpm']);

async function digestFile(filename) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

async function main() {
  const directory = path.resolve(process.argv[2] || 'dist');
  const entries = await fsp.readdir(directory, { withFileTypes: true });
  const artifacts = entries
    .filter((entry) => entry.isFile() && RELEASE_EXTENSIONS.has(path.extname(entry.name)))
    .map((entry) => path.join(directory, entry.name))
    .sort();
  if (artifacts.length === 0) throw new Error(`No release artifacts found in ${directory}`);

  for (const artifact of artifacts) {
    const line = `${await digestFile(artifact)}  ${path.basename(artifact)}\n`;
    await fsp.writeFile(`${artifact}.sha256`, line, { mode: 0o644 });
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
