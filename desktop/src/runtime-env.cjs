const path = require('node:path');

// A newly installed Podman binary may not be visible in Desktop's inherited
// PATH until the next login. The CLI still owns runtime selection and every
// Podman command; Desktop only supplies the conventional executable locations
// in the environment of its bundled CLI child process.
function knownRuntimeDirectories(platform, env) {
  if (platform === 'darwin') return ['/opt/podman/bin', '/usr/local/bin', '/opt/homebrew/bin'];
  if (platform === 'win32') {
    return [
      env.LOCALAPPDATA && path.join(env.LOCALAPPDATA, 'Programs', 'Podman'),
      env.ProgramFiles && path.join(env.ProgramFiles, 'Podman'),
      env.ProgramFiles && path.join(env.ProgramFiles, 'RedHat', 'Podman'),
    ].filter(Boolean);
  }
  return ['/usr/local/bin', '/usr/bin', '/bin'];
}

module.exports = { knownRuntimeDirectories };
