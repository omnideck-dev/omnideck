// Seeds a throwaway desktop profile into one of the states worth looking at, so
// a scenario can be reached without waiting for one to occur naturally.
//
//   node scripts/seed-profile.cjs <profile-dir> <state> [imageRef]
//
// States:
//   fresh          nothing installed — Welcome, then a first install
//   installed      a finished install that opens straight to the app
//   update-ready   an update waiting to be applied at the next launch
//   old-port       an install still on the port the command line tool uses
//   stale-version  an install recorded as older than it is, so a registry check
//                  finds a real release to offer
//   legacy-record  the state file shape written before the version was tracked
const fsp = require('node:fs/promises');
const path = require('node:path');

const { readSetupState, writeSetupState } = require('../src/setup-state.cjs');
const { readUpdateState, writeUpdateState } = require('../src/update-state.cjs');
const { APP_VERSION } = require('../src/runtime.cjs');

const INSTALLED_REF = `ghcr.io/omnideck-dev/omnideck@sha256:${'a'.repeat(64)}`;

function installed(profile, { imageVersion = APP_VERSION, imageRef = INSTALLED_REF } = {}) {
  return writeSetupState(profile, {
    status: 'complete',
    reason: 'first-run',
    appVersion: APP_VERSION,
    imageVersion,
    imageRef,
  });
}

const STATES = {
  // Nothing to write. An empty profile is a computer omnideck has never run on.
  fresh: async () => {},
  installed: (profile) => installed(profile),
  // A local image reference costs nothing to install: podman already has it, so
  // the pull is skipped and the whole update path runs without a network.
  'update-ready': async (profile, imageRef) => {
    await installed(profile);
    await writeUpdateState(profile, {
      automatic: true,
      version: '99.0.0',
      imageRef: imageRef || 'localhost/omnideck/runtime:local-update',
    });
  },
  'old-port': async (profile) => {
    await installed(profile);
    await fsp.writeFile(path.join(profile, 'runtime', 'app-port'), '2337\n');
  },
  // The image on the computer is current; only the recorded version is old, so
  // a registry check finds a newer release and the notice has something to say.
  // Installing it re-installs what is already there.
  'stale-version': (profile, imageRef) => installed(profile, {
    imageVersion: '0.0.1',
    imageRef: imageRef || INSTALLED_REF,
  }),
  'legacy-record': (profile) => fsp.writeFile(
    path.join(profile, 'setup-state.json'),
    `${JSON.stringify({
      schemaVersion: 1,
      status: 'complete',
      reason: 'first-run',
      appVersion: '0.1.0-alpha.5',
      imageRef: INSTALLED_REF,
      imageDigest: `sha256:${'a'.repeat(64)}`,
      updatedAt: new Date().toISOString(),
    }, null, 2)}\n`,
    { mode: 0o600 },
  ),
};

async function main() {
  const [profile, state, imageRef] = process.argv.slice(2);
  if (!STATES[state] || !profile) {
    throw new Error(`Usage: seed-profile.cjs <profile-dir> <${Object.keys(STATES).join('|')}> [imageRef]`);
  }
  await fsp.rm(profile, { recursive: true, force: true });
  await fsp.mkdir(path.join(profile, 'runtime'), { recursive: true });
  await STATES[state](profile, imageRef);

  console.log(`${state} -> ${profile}`);
  console.log('  setup-state :', JSON.stringify(await readSetupState(profile)));
  console.log('  update-state:', JSON.stringify(await readUpdateState(profile)));
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
