#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export const RELEASE_NOTE_TYPES = [
  'added',
  'changed',
  'deprecated',
  'removed',
  'fixed',
  'security',
];

export const RELEASE_NOTE_TARGETS = ['app', 'desktop'];

const CONVENTIONAL_TITLE =
  /^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-z0-9][a-z0-9._/-]*\))?!?: \S.*$/;

const scriptPath = fileURLToPath(import.meta.url);
const repositoryRoot = resolve(dirname(scriptPath), '..');
const defaultNotesDirectory = join(repositoryRoot, 'release-notes.d');

export function isConventionalTitle(title) {
  return CONVENTIONAL_TITLE.test(String(title || '').trim());
}

export function parseFragment(text, source = '<fragment>') {
  const normalized = String(text).replace(/\r\n/g, '\n');
  const match = normalized.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) {
    throw new Error(`${source}: expected YAML front matter between --- lines`);
  }

  const metadata = {};
  for (const line of match[1].split('\n')) {
    const field = line.match(/^([a-z][a-z0-9-]*):\s*(\S.*)$/);
    if (!field) {
      throw new Error(`${source}: invalid front matter line: ${line}`);
    }
    if (field[1] in metadata) {
      throw new Error(`${source}: duplicate ${field[1]} field`);
    }
    metadata[field[1]] = field[2].trim();
  }

  const unknown = Object.keys(metadata).filter(
    (key) => !['target', 'type', 'area'].includes(key),
  );
  if (unknown.length) {
    throw new Error(`${source}: unsupported field(s): ${unknown.join(', ')}`);
  }
  if (!RELEASE_NOTE_TYPES.includes(metadata.type)) {
    throw new Error(
      `${source}: type must be one of ${RELEASE_NOTE_TYPES.join(', ')}`,
    );
  }
  if (!RELEASE_NOTE_TARGETS.includes(metadata.target)) {
    throw new Error(
      `${source}: target must be one of ${RELEASE_NOTE_TARGETS.join(', ')}`,
    );
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(metadata.area || '')) {
    throw new Error(`${source}: area must be a lowercase kebab-case name`);
  }

  const body = match[2].trim();
  if (!body) {
    throw new Error(`${source}: release-note text must not be empty`);
  }
  if (/^#{1,6}\s/m.test(body)) {
    throw new Error(`${source}: use prose, not headings, inside a fragment`);
  }

  return {
    target: metadata.target,
    type: metadata.type,
    area: metadata.area,
    body,
    source,
  };
}

export function fragmentsForTarget(fragments, target) {
  if (!RELEASE_NOTE_TARGETS.includes(target)) {
    throw new Error(`--target must be one of ${RELEASE_NOTE_TARGETS.join(', ')}`);
  }
  return fragments.filter((fragment) => fragment.target === target);
}

export function parseChangedFiles(text) {
  return String(text || '')
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const columns = line.split('\t');
      return {
        status: columns[0],
        path: columns.at(-1),
      };
    });
}

function releaseNoteSection(body) {
  const withoutComments = String(body || '').replace(/<!--[\s\S]*?-->/g, '');
  const lines = withoutComments.split(/\r?\n/);
  const heading = lines.findIndex((line) =>
    /^##\s+Release note\s*$/i.test(line),
  );
  if (heading === -1) return '';

  const section = [];
  for (const line of lines.slice(heading + 1)) {
    if (/^##\s+/.test(line)) break;
    section.push(line);
  }
  return section.join('\n').trim();
}

function isFragmentPath(path) {
  return (
    path.startsWith('release-notes.d/') &&
    path.endsWith('.md') &&
    basename(path).toLowerCase() !== 'readme.md'
  );
}

export function validatePullRequest(
  { title, body = '', labels = [], changedFiles = [] },
  { readFragment = (path) => readFileSync(join(repositoryRoot, path), 'utf8') } = {},
) {
  const errors = [];

  if (!isConventionalTitle(title)) {
    errors.push(
      'PR title must use Conventional Commits, for example feat(desktop): add native zoom',
    );
  }

  const fragments = changedFiles.filter(
    ({ status, path }) => status[0] !== 'D' && isFragmentPath(path),
  );
  const addedFragments = fragments.filter(({ status }) =>
    ['A', 'C', 'R'].includes(status[0]),
  );
  const hasNoNoteLabel = labels.includes('release-note:none');

  if (hasNoNoteLabel && addedFragments.length) {
    errors.push(
      'Choose either release-note fragments or the release-note:none label, not both',
    );
  } else if (hasNoNoteLabel) {
    const section = releaseNoteSection(body);
    if (!/^None:\s+\S/im.test(section)) {
      errors.push(
        'release-note:none requires "None: <reason>" under the PR body Release note heading',
      );
    }

    const titleType = String(title || '').match(/^([a-z]+)/)?.[1];
    if (titleType === 'feat' || /!\s*:/.test(String(title || ''))) {
      errors.push('Features and breaking changes must include a release-note fragment');
    }
  } else if (!addedFragments.length) {
    errors.push(
      'Add a release-notes.d/*.md fragment or apply release-note:none with a reason',
    );
  }

  for (const { path } of fragments) {
    try {
      parseFragment(readFragment(path), path);
    } catch (error) {
      errors.push(error.message);
    }
  }

  return errors;
}

function changedFilesForEvent(pullRequest) {
  if (process.env.RELEASE_NOTES_CHANGED_FILES !== undefined) {
    return parseChangedFiles(process.env.RELEASE_NOTES_CHANGED_FILES);
  }

  const range = `${pullRequest.base.sha}...${pullRequest.head.sha}`;
  const output = execFileSync('git', ['diff', '--name-status', range], {
    cwd: repositoryRoot,
    encoding: 'utf8',
  });
  return parseChangedFiles(output);
}

function fragmentFiles(directory = defaultNotesDirectory) {
  if (!existsSync(directory)) {
    return [];
  }
  return readdirSync(directory, { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isFile() &&
        entry.name.endsWith('.md') &&
        entry.name.toLowerCase() !== 'readme.md',
    )
    .map((entry) => join(directory, entry.name))
    .sort();
}

export function renderReleaseNotes(fragments, version = '', target = '') {
  if (!fragments.length) {
    throw new Error('No release-note fragments are available');
  }

  const title =
    target === 'app' && version
      ? `# omnideck app ${version}`
      : version
        ? `# Release notes for ${version}`
        : '# Release notes';
  const lines = [title, ''];

  for (const type of RELEASE_NOTE_TYPES) {
    const matches = fragments.filter((fragment) => fragment.type === type);
    if (!matches.length) continue;

    lines.push(`## ${type[0].toUpperCase()}${type.slice(1)}`, '');
    for (const fragment of matches) {
      const area = fragment.area
        .split('-')
        .map((part) => part[0].toUpperCase() + part.slice(1))
        .join(' ');
      const prose = fragment.body.replace(/\s+/g, ' ').trim();
      lines.push(`- **${area}:** ${prose}`);
    }
    lines.push('');
  }

  return `${lines.join('\n').trimEnd()}\n`;
}

function loadFragments() {
  return fragmentFiles().map((path) =>
    parseFragment(readFileSync(path, 'utf8'), relative(repositoryRoot, path)),
  );
}

function optionValue(args, name) {
  const index = args.indexOf(name);
  if (index === -1) return '';
  if (!args[index + 1]) throw new Error(`${name} requires a value`);
  return args[index + 1];
}

function validatePrCommand() {
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (!eventPath) {
    console.log('GITHUB_EVENT_PATH is not set; PR metadata validation skipped.');
    return;
  }

  const event = JSON.parse(readFileSync(eventPath, 'utf8'));
  if (!event.pull_request) {
    console.log('This event has no pull request; PR metadata validation skipped.');
    return;
  }

  const errors = validatePullRequest({
    title: event.pull_request.title,
    body: event.pull_request.body || '',
    labels: event.pull_request.labels.map((label) => label.name),
    changedFiles: changedFilesForEvent(event.pull_request),
  });

  if (errors.length) {
    for (const error of errors) console.error(`::error::${error}`);
    process.exitCode = 1;
    return;
  }
  console.log('Release-note policy passed.');
}

function main() {
  const [command, ...args] = process.argv.slice(2);

  if (command === 'validate-pr') {
    validatePrCommand();
    return;
  }

  if (command === 'validate-fragments') {
    const fragments = loadFragments();
    console.log(`Validated ${fragments.length} release-note fragment(s).`);
    return;
  }

  if (command === 'generate') {
    const target = optionValue(args, '--target');
    const output = renderReleaseNotes(
      fragmentsForTarget(loadFragments(), target),
      optionValue(args, '--version'),
      target,
    );
    const outputPath = optionValue(args, '--output');
    if (!outputPath) {
      process.stdout.write(output);
      return;
    }

    const resolvedOutput = resolve(repositoryRoot, outputPath);
    if (
      resolvedOutput !== repositoryRoot &&
      !resolvedOutput.startsWith(`${repositoryRoot}${sep}`)
    ) {
      throw new Error('--output must stay inside the repository');
    }
    mkdirSync(dirname(resolvedOutput), { recursive: true });
    writeFileSync(resolvedOutput, output, 'utf8');
    console.log(`Wrote ${relative(repositoryRoot, resolvedOutput)}`);
    return;
  }

  if (command === 'check-consumed') {
    const target = optionValue(args, '--target');
    const fragments = fragmentsForTarget(loadFragments(), target);
    if (fragments.length) {
      throw new Error(
        `Outstanding ${target} release-note fragment(s):\n${fragments
          .map((fragment) => fragment.source)
          .join('\n')}`,
      );
    }
    console.log(`All ${target} release-note fragments have been consumed.`);
    return;
  }

  throw new Error(
    'Usage: node scripts/release-notes.mjs <validate-pr|validate-fragments|generate|check-consumed> [--target TARGET] [--version VERSION] [--output PATH]',
  );
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  try {
    main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
