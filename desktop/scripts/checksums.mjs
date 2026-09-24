import { createHash } from 'node:crypto';
import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(process.argv[2] || '');
if (!process.argv[2]) {
  throw new Error('Usage: node scripts/checksums.mjs <bundle directory>');
}

const extensions = new Set(['.appimage', '.deb', '.dmg', '.exe', '.rpm']);
const artifacts = [];
async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) await walk(candidate);
    else if (extensions.has(path.extname(entry.name).toLowerCase())) artifacts.push(candidate);
  }
}

await walk(root);
if (artifacts.length === 0) throw new Error(`No installer artifacts found under ${root}.`);
for (const artifact of artifacts.sort()) {
  const digest = createHash('sha256').update(await readFile(artifact)).digest('hex');
  const checksum = `${artifact}.sha256`;
  await writeFile(checksum, `${digest}  ${path.basename(artifact)}\n`, 'utf8');
  process.stdout.write(`${checksum}\n`);
}
