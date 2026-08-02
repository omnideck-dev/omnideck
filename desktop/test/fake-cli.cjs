#!/usr/bin/env node
// Stands in for the command line tool. Every shape it prints was captured from
// the real one, including the parts that read oddly: status answers a question
// about something that is not running and still exits non-zero, and a stray
// non-JSON line on stderr is normal rather than a sign of trouble.
//
// What it does is chosen by OMNIDECK_FAKE_CLI, so one file covers every case.
const mode = process.env.OMNIDECK_FAKE_CLI || 'ok';
const command = process.argv[2];
const emit = (value) => process.stdout.write(`${JSON.stringify(value)}\n`);

if (mode === 'silent') {
  process.stderr.write('something went very wrong\n');
  process.exit(1);
}

if (mode === 'not-installed') {
  emit({ error: { code: 'NOT_INSTALLED', message: 'Omnideck is not set up. Run: omnideck add' } });
  process.exit(1);
}

if (command === 'setup' && process.argv.includes('--suggest-defaults')) {
  emit({ name: 'omnideck', webUiPort: '2339' });
  process.exit(0);
}

if (command === 'setup') {
  process.stderr.write('a line that is not json\n');
  for (const stage of ['check_availability', 'create_home_volume', 'create_state_volume']) {
    emit({ stage, state: 'start' });
    emit({ stage, state: 'done' });
  }
  emit({ stage: 'pull_image', state: 'start' });
  emit({ stage: 'pull_image', state: 'progress', detail: 'Copying blob abc123' });
  if (mode === 'pull-fails') {
    emit({
      stage: 'pull_image',
      state: 'error',
      error: { code: 'INTERNAL_ERROR', message: 'podman pull: exit status 125' },
    });
    process.exit(1);
  }
  emit({ stage: 'pull_image', state: 'done' });
  emit({ stage: 'run_container', state: 'start' });
  emit({ stage: 'run_container', state: 'done' });
  emit({ stage: 'save_config', state: 'start' });
  emit({ stage: 'save_config', state: 'done' });
  emit({ stage: 'complete', state: 'done', result: { name: 'desktop', webUiPort: '2338' } });
  process.exit(0);
}

if (command === 'status') {
  if (mode === 'no-container') {
    // What the real one answers when the container is gone: a status, not an
    // error about a missing container.
    emit({ name: 'omnideck-desktop', container: 'omnideck-desktop', status: 'unknown', webUiPort: '2338' });
    process.exit(1);
  }
  if (mode === 'stopped') {
    emit({ name: 'omnideck-desktop', container: 'omnideck-desktop', status: 'exited', webUiPort: '2338' });
    process.exit(1);
  }
  emit({ name: 'omnideck-desktop', container: 'omnideck-desktop', status: 'running', webUiPort: '2338' });
  process.exit(0);
}

if (command === 'start' || command === 'stop') {
  if (mode === 'no-container') {
    emit({ error: { code: 'CONTAINER_NOT_FOUND', message: 'container "omnideck-desktop" was not found' } });
    process.exit(1);
  }
  if (mode === 'no-engine') {
    emit({ error: { code: 'ENGINE_NOT_FOUND', message: 'Podman is not installed' } });
    process.exit(1);
  }
  emit({ name: 'omnideck-desktop', status: command === 'start' ? 'running' : 'exited' });
  process.exit(0);
}

emit({ error: { code: 'MISSING_SUBCOMMAND', message: `unknown command ${command}` } });
process.exit(1);
