// What the application remembers about updates between launches.
//
// Four things live here. The version someone chose to skip, so it stays
// skipped. The version they chose to put off until next time, which installs
// itself at the next launch without turning anything else on. Whether they
// asked for updates to be applied on their own — read from the application's
// own settings while it is running and kept here, because at the moment it
// matters the application is not running yet. And the last answer the registry
// gave, so a relaunch has something to show without asking again straight away.
const fsp = require('node:fs/promises');
const path = require('node:path');

const UPDATE_STATE_SCHEMA = 1;
const UPDATE_STATE_FILENAME = 'update-state.json';

// The two preferences start where the application's own defaults start, so a
// launch that happens before they have ever been read behaves the same way the
// application would.
const EMPTY = Object.freeze({
  schemaVersion: UPDATE_STATE_SCHEMA,
  skippedVersion: null,
  deferredVersion: null,
  automatic: true,
  notify: true,
  checkedAt: null,
  version: null,
  imageRef: null,
});

function isText(value) {
  return value === null || typeof value === 'string';
}

function isUpdateState(value) {
  return Boolean(
    value
    && value.schemaVersion === UPDATE_STATE_SCHEMA
    && isText(value.skippedVersion)
    && isText(value.deferredVersion)
    && typeof value.automatic === 'boolean'
    && typeof value.notify === 'boolean'
    && isText(value.checkedAt)
    && isText(value.version)
    && isText(value.imageRef),
  );
}

// Never throws. Every field has a safe absence, and a file that cannot be read
// is indistinguishable from one that was never written: no update is known, and
// nothing has been skipped.
async function readUpdateState(userDataPath) {
  try {
    const value = JSON.parse(
      await fsp.readFile(path.join(userDataPath, UPDATE_STATE_FILENAME), 'utf8'),
    );
    return isUpdateState(value) ? value : { ...EMPTY };
  } catch {
    return { ...EMPTY };
  }
}

// Merges over what is already stored, so a caller that knows one field does not
// have to know the rest.
async function writeUpdateState(userDataPath, changes) {
  const value = { ...await readUpdateState(userDataPath), ...changes };
  value.schemaVersion = UPDATE_STATE_SCHEMA;
  if (!isUpdateState(value)) throw new Error('The update state is invalid.');

  await fsp.mkdir(userDataPath, { recursive: true });
  const destination = path.join(userDataPath, UPDATE_STATE_FILENAME);
  const temporary = `${destination}.${process.pid}.${Date.now()}.partial`;
  await fsp.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  try {
    await fsp.rename(temporary, destination);
  } catch (error) {
    if (!['EEXIST', 'EPERM'].includes(error.code)) throw error;
    await fsp.rm(destination, { force: true });
    await fsp.rename(temporary, destination);
  }
  return value;
}

module.exports = {
  UPDATE_STATE_FILENAME,
  UPDATE_STATE_SCHEMA,
  isUpdateState,
  readUpdateState,
  writeUpdateState,
};
