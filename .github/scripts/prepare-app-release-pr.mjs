#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

function run(command, args) {
  return execFileSync(command, args, { encoding: 'utf8' }).trim();
}
const git = (...args) => run('git', args);
const gh = (...args) => run('gh', args);
const api = path => JSON.parse(gh('api', path));
const workflows = ['publish.yml', 'release-note-policy.yml'];

export function dispatchedRun(runs, { afterId, sha, branch }) {
  return runs.filter(r => r.id > afterId && r.head_sha === sha
    && r.head_branch === branch && r.event === 'workflow_dispatch')
    .sort((a, b) => b.id - a.id)[0];
}
export function assertUnchangedMain(sourceSha, mainSha) {
  if (mainSha !== sourceSha) throw new Error('Main advanced during preparation; rerun to plan a fresh release');
}

async function main() {
  const plan = JSON.parse(readFileSync(process.argv[2], 'utf8'));
  const repo = process.env.GITHUB_REPOSITORY;
  if (!repo || !/^[a-f0-9]{40}$/.test(plan.source_sha)
      || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(plan.version)) {
    throw new Error('Invalid repository, version, or source SHA');
  }
  const branch = `release/auto-app-${plan.version}-${plan.source_sha.slice(0, 7)}`;
  if (git('ls-remote', '--heads', 'origin', `refs/heads/${branch}`)) {
    git('fetch', 'origin', `refs/heads/${branch}`);
    // Reuse an identical preparation after a failed/partial run. Never replace
    // a branch containing different changes, and never force-push.
    git('diff', '--exit-code', 'HEAD', 'FETCH_HEAD');
    git('checkout', '--detach', 'FETCH_HEAD');
  } else {
    git('push', 'origin', `HEAD:refs/heads/${branch}`);
  }
  const sha = git('rev-parse', 'HEAD');
  const open = JSON.parse(gh('pr', 'list', '--repo', repo, '--head', branch,
    '--base', 'main', '--state', 'open', '--json', 'number'));
  let number = open[0]?.number;
  if (!number) {
    const bodyFile = join(process.env.RUNNER_TEMP, 'app-release-pr.md');
    writeFileSync(bodyFile, `Prepare app ${plan.version} from tested source ${plan.source_sha}.\n\n`
      + 'Aggregate reviewed app fragments and record the source digest selection. Publication follows successful checks and a normal PR merge.\n\n'
      + '## Release note\n\nNone: Aggregates previously reviewed app fragments into release metadata without changing application code.\n');
    try {
      const url = gh('pr', 'create', '--repo', repo, '--base', 'main', '--head', branch,
        '--title', `chore(release): prepare app ${plan.version}`, '--body-file', bodyFile,
        '--label', 'release-note:none');
      number = Number(url.split('/').at(-1));
    } catch (error) {
      throw new Error('Could not create the release PR. Enable “Allow GitHub Actions to create and approve pull requests” in organization/repository Actions settings. No version was published.', { cause: error });
    }
  }
  console.log(`Preparing ${repo}#${number} at ${sha}`);
  const runsPath = workflow => `repos/${repo}/actions/workflows/${workflow}/runs?head_sha=${sha}&branch=${branch}&event=workflow_dispatch&per_page=100`;
  const pending = new Map();
  for (const workflow of workflows) {
    const afterId = Math.max(0, ...api(runsPath(workflow)).workflow_runs.map(r => r.id));
    pending.set(workflow, { afterId, sha, branch });
    gh('workflow', 'run', workflow, '--repo', repo, '--ref', branch,
      ...(workflow === 'release-note-policy.yml' ? ['-f', `pull_request_number=${number}`] : []));
  }
  // GITHUB_TOKEN-created PRs do not reliably start ordinary PR workflows.
  // Explicit dispatch runs both real checks on the preparation branch SHA.
  const deadline = Date.now() + 12 * 60 * 1000;
  while (pending.size && Date.now() < deadline) {
    for (const [workflow, selection] of pending) {
      const selected = dispatchedRun(api(runsPath(workflow)).workflow_runs, selection);
      if (!selected || selected.status !== 'completed') continue;
      if (selected.conclusion !== 'success') throw new Error(`${workflow} failed: ${selected.html_url}`);
      console.log(`${workflow} passed: ${selected.html_url}`);
      pending.delete(workflow);
    }
    if (pending.size) await new Promise(resolve => setTimeout(resolve, 15000));
  }
  if (pending.size) throw new Error('Timed out waiting for release PR checks; rerun to resume');
  assertUnchangedMain(plan.source_sha, api(`repos/${repo}/git/ref/heads/main`).object.sha);
  gh('pr', 'merge', String(number), '--repo', repo, '--squash', '--match-head-commit', sha);
  const merged = JSON.parse(gh('pr', 'view', String(number), '--repo', repo, '--json', 'state,mergeCommit'));
  if (merged.state !== 'MERGED') throw new Error('Release PR was not merged');
  git('fetch', 'origin', 'main');
  git('checkout', '--detach', merged.mergeCommit.oid);
  // Verify the merged release snapshot contains only the planned metadata.
  const changes = git('diff', '--name-only', plan.source_sha, 'HEAD').split('\n');
  if (changes.some(p => !p.startsWith('release-notes.d/')
      && p !== `docs/releases/app-v${plan.version}.md`
      && p !== `docs/releases/app-v${plan.version}.json`)) {
    throw new Error('Merged release snapshot includes unexpected changes; refusing publication');
  }
  console.log(`Release notes merged in ${repo}#${number}`);
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(error.message); process.exitCode = 1; });
}
