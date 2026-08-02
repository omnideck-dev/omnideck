const fsp = require('node:fs/promises');
const path = require('node:path');

const SETUP_STATE_SCHEMA = 1;
const SETUP_STATE_FILENAME = 'setup-state.json';
const SETUP_STATUSES = new Set(['in-progress', 'complete']);
const SETUP_REASONS = new Set(['first-run', 'resume', 'update', 'repair']);

function isSetupState(value) {
  return Boolean(
    value
    && value.schemaVersion === SETUP_STATE_SCHEMA
    && SETUP_STATUSES.has(value.status)
    && SETUP_REASONS.has(value.reason)
    && typeof value.appVersion === 'string'
    && typeof value.imageVersion === 'string'
    && typeof value.imageRef === 'string'
    && typeof value.updatedAt === 'string',
  );
}

async function readSetupState(userDataPath) {
  try {
    const value = JSON.parse(
      await fsp.readFile(path.join(userDataPath, SETUP_STATE_FILENAME), 'utf8'),
    );
    return isSetupState(value) ? value : null;
  } catch {
    return null;
  }
}

async function writeSetupState(userDataPath, state) {
  const value = {
    schemaVersion: SETUP_STATE_SCHEMA,
    status: state.status,
    reason: state.reason,
    appVersion: state.appVersion,
    imageVersion: state.imageVersion,
    imageRef: state.imageRef,
    imageDigest: state.imageRef.match(/@(?<digest>sha256:[a-f0-9]{64})$/)?.groups?.digest || null,
    updatedAt: new Date().toISOString(),
  };
  if (!isSetupState(value)) throw new Error('The setup state is invalid.');

  await fsp.mkdir(userDataPath, { recursive: true });
  const destination = path.join(userDataPath, SETUP_STATE_FILENAME);
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
  SETUP_REASONS,
  SETUP_STATE_FILENAME,
  SETUP_STATE_SCHEMA,
  isSetupState,
  readSetupState,
  writeSetupState,
};
