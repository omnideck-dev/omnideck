const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const { version } = require('../package.json');

async function digestFile(filename) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}

async function main() {
  const archivePath = path.resolve(process.argv[2] || '');
  const architecture = process.argv[3];
  if (!archivePath || !['amd64', 'arm64'].includes(architecture)) {
    throw new Error(
      'Usage: node scripts/prepare-bundled-image.cjs <omnideck-image.oci.tar> <amd64|arm64>',
    );
  }
  await fsp.access(archivePath, fs.constants.R_OK);
  const archive = path.basename(archivePath);
  if (archive !== 'omnideck-image.oci.tar') {
    throw new Error('The bundled image archive must be named omnideck-image.oci.tar.');
  }

  const manifest = {
    schemaVersion: 1,
    appVersion: version,
    architecture,
    imageRef: `localhost/omnideck/runtime:${version}`,
    archive,
    archiveSha256: await digestFile(archivePath),
  };
  const destination = path.join(path.dirname(archivePath), 'image-manifest.json');
  await fsp.writeFile(destination, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o644 });
  process.stdout.write(`${destination}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
