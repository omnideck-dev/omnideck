const fsp = require('node:fs/promises');
const path = require('node:path');

const { version } = require('../package.json');

async function main() {
  const imageRef = process.argv[2] || '';
  if (!/^ghcr\.io\/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$/.test(imageRef)) {
    throw new Error(
      'Usage: node scripts/prepare-runtime-image.cjs '
      + '<ghcr.io/owner/image@sha256:digest>',
    );
  }

  const destinationRoot = path.resolve('build/runtime');
  const manifest = {
    schemaVersion: 2,
    appVersion: version,
    imageRef,
  };
  const destination = path.join(destinationRoot, 'image-manifest.json');
  await fsp.mkdir(destinationRoot, { recursive: true });
  await fsp.writeFile(destination, `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o644 });
  process.stdout.write(`${destination}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
