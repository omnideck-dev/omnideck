// Publishing this installation where the command line tool looks for the ones
// it manages, so both see the same omnideck.
//
// The command line tool builds its list from the instance files in its own
// configuration directory. Writing one there is enough for it to list this
// installation, report its status, follow its logs and start or stop it —
// nothing on that side has to change, and the installations it set up itself
// are untouched.
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const INSTANCE_NAME = 'desktop';

// Where the command line tool keeps its configuration, by the same rules it
// uses: the operating system's own configuration location, with an environment
// override that takes precedence.
function configDirectory(platform = process.platform, env = process.env) {
  if (env.OMNIDECK_CONFIG_DIR) return path.resolve(env.OMNIDECK_CONFIG_DIR);
  const home = os.homedir();
  if (platform === 'win32') {
    return path.join(env.APPDATA || path.join(home, 'AppData', 'Roaming'), 'omnideck-cli');
  }
  if (platform === 'darwin') {
    return path.join(home, 'Library', 'Application Support', 'omnideck-cli');
  }
  return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'omnideck-cli');
}

function instancePath(platform, env) {
  return path.join(configDirectory(platform, env), 'instances', `${INSTANCE_NAME}.yaml`);
}

// Only the fields the command line tool reads, in the shape it reads them.
// Everything here is a plain value, so no quoting is needed and no YAML library
// with it.
function instanceDocument({ containerName, homeVolume, stateVolume, port, image, installedAt }) {
  return [
    '# Written by the omnideck application so the command line tool can see it.',
    '# Edits are replaced the next time omnideck starts.',
    `container_name: ${containerName}`,
    `home_volume: ${homeVolume}`,
    `state_volume: ${stateVolume}`,
    'memory: 2g',
    'shm_size: 1024m',
    `web_ui_port: "${port}"`,
    `image: ${image}`,
    `installed_at: ${installedAt}`,
    '',
  ].join('\n');
}

// Best effort by design: the command line tool not being installed, or its
// configuration directory not being writable, is not a reason for omnideck to
// fail to start.
async function publishInstance(details, platform = process.platform, env = process.env) {
  const destination = instancePath(platform, env);
  try {
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await fsp.writeFile(destination, instanceDocument(details), { mode: 0o600 });
    return destination;
  } catch {
    return null;
  }
}

module.exports = {
  INSTANCE_NAME,
  configDirectory,
  instanceDocument,
  instancePath,
  publishInstance,
};
